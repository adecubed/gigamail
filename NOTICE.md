# Data for the gigamail.ai email checker

Rebuilt daily by .github/workflows/checker-lists.yml in adecubed/gigamail.

Known bad hosts come from:

- phishing-database: MIT, https://github.com/Phishing-Database/Phishing.Database
- phishing-filter: CC BY-SA 4.0, https://gitlab.com/malware-filter/phishing-filter (from OpenPhish and Phishing.Database)
- urlhaus: CC0, https://urlhaus.abuse.ch (via https://gitlab.com/malware-filter/urlhaus-filter, CC0 and MIT)

Popular sites: Tranco, https://tranco-list.eu (built from Chrome UX Report, Cloudflare Radar and other rankings).

The hashed lists are an adaptation of those sources and are shared under the same terms: CC BY-SA 4.0 for what comes from phishing-filter.
