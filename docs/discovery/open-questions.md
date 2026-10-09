# Open questions

## For the hiring team
1. Which document types dominate travel-claim volume, and in which languages?
2. What core claims system and API style do the claims teams use (REST, SOAP, batch files)?
3. Which model providers and cloud regions are approved today?
4. How is handling time measured, and where do claims wait longest?
5. Is there an existing fraud scoring system ClaimPilot should feed instead of replacing?

## For the build (decide or validate)
6. Routing thresholds (3,000 EUR senior limit, 500 EUR fast-track cap, 3-day early-claim window) are guesses.
7. Is one deductible per event the common reading of travel VPP, or per coverage section?
8. Which exchange rate date do handlers use in practice: event date, invoice date or payment date?
9. Do handlers accept a bounding-box link as enough evidence, or do they want the cropped image inline?
