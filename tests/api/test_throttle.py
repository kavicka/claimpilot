"""Login throttle: counters in Redis shared by all tasks, a bounded in-process fallback, and the
client address the counters are keyed by. No database needed."""

from types import SimpleNamespace

from apitools import FakeRedis

from claimpilot_api.throttle import LoginThrottle, client_ip


async def fail(t, redis, user="u", ip="1.1.1.1", times=1):
    for _ in range(times):
        await t.failed(redis, user, ip)


async def test_five_failures_block_that_user_from_that_address():
    t, r = LoginThrottle(), FakeRedis()
    await fail(t, r, times=4)
    assert not await t.blocked(r, "u", "1.1.1.1")
    await fail(t, r)
    assert await t.blocked(r, "u", "1.1.1.1")


async def test_the_counter_is_per_user_and_per_address():
    t, r = LoginThrottle(), FakeRedis()
    await fail(t, r, times=5)
    assert not await t.blocked(r, "other", "1.1.1.1")
    assert not await t.blocked(r, "u", "2.2.2.2")


async def test_the_username_is_compared_without_case_and_spaces():
    t, r = LoginThrottle(), FakeRedis()
    await fail(t, r, user="Handler.Demo ", times=5)
    assert await t.blocked(r, "handler.demo", "1.1.1.1")


async def test_counters_expire_on_their_own_and_hold_no_username():
    t, r = LoginThrottle(window_s=900), FakeRedis()
    await fail(t, r)
    (key,) = r.data
    assert r.ttl[key] == 900
    assert "u" not in key.split(":")[-1] and "1.1.1.1" not in key


async def test_the_counter_is_shared_between_tasks_through_redis():
    r = FakeRedis()
    a, b = LoginThrottle(), LoginThrottle()  # two ECS tasks, one Redis
    await fail(a, r, times=3)
    await fail(b, r, times=2)
    assert await a.blocked(r, "u", "1.1.1.1")


async def test_a_good_login_clears_the_counter():
    t, r = LoginThrottle(), FakeRedis()
    await fail(t, r, times=4)
    await t.succeeded(r, "u", "1.1.1.1")
    await fail(t, r, times=4)
    assert not await t.blocked(r, "u", "1.1.1.1")


async def test_without_redis_a_bounded_memory_counter_takes_over():
    t = LoginThrottle()
    await fail(t, None, times=5)
    assert await t.blocked(None, "u", "1.1.1.1")
    t2 = LoginThrottle()
    await fail(t2, SimpleNamespace(), times=5)  # an object that is no Redis client
    assert await t2.blocked(SimpleNamespace(), "u", "1.1.1.1")


async def test_when_redis_goes_down_the_throttle_keeps_working():
    t, r = LoginThrottle(), FakeRedis()
    r.down = True
    await fail(t, r, times=5)
    assert await t.blocked(r, "u", "1.1.1.1")
    assert not await t.blocked(r, "v", "1.1.1.1")


async def test_the_memory_fallback_does_not_grow_without_bound():
    t = LoginThrottle(max_entries=100)
    for i in range(1000):
        await t.failed(None, f"user{i}", "1.1.1.1")
    assert len(t._memory) == 100
    assert await t.blocked(None, "user999", "1.1.1.1") is False  # one failure is not a block


async def test_a_busy_attacker_does_not_push_a_blocked_user_out_of_memory():
    t = LoginThrottle(max_entries=100)
    await fail(t, None, user="victim", times=5)
    for i in range(50):
        await t.failed(None, f"noise{i}", "9.9.9.9")
    assert await t.blocked(None, "victim", "1.1.1.1")


def request(peer="10.0.0.5", forwarded=None):
    headers = {"x-forwarded-for": forwarded} if forwarded else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


def test_the_client_is_the_tcp_peer_by_default():
    assert client_ip(request(forwarded="6.6.6.6"), trust_forwarded_for=False) == "10.0.0.5"


def test_behind_the_load_balancer_the_forwarded_address_is_used():
    assert client_ip(request(forwarded="203.0.113.7"), trust_forwarded_for=True) == "203.0.113.7"


def test_a_forged_first_hop_does_not_choose_the_address():
    # The balancer appends the real peer; whatever the client put before it is not trusted.
    forwarded = "1.2.3.4, 203.0.113.7"
    assert client_ip(request(forwarded=forwarded), trust_forwarded_for=True) == "203.0.113.7"


def test_no_header_and_no_peer_fall_back_safely():
    assert client_ip(request(), trust_forwarded_for=True) == "10.0.0.5"
    assert (
        client_ip(SimpleNamespace(client=None, headers={}), trust_forwarded_for=False) == "unknown"
    )
