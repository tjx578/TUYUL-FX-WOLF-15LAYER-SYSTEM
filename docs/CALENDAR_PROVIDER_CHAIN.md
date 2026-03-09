# Calendar Provider Chain (PR2/PR3)

## Selection Flags

- `NEWS_PROVIDER=forexfactory`
  - Chain: `forexfactory_json -> forexfactory_xml -> finnhub`
- `NEWS_PROVIDER=finnhub`
  - Chain: `finnhub -> forexfactory_json -> forexfactory_xml`
- `NEWS_PROVIDER=off`
  - Raises `NoProvidersConfiguredError`

## HTML Fallback

- Disabled by default.
- Enable with `NEWS_FF_HTML_FALLBACK_ENABLED=true`.
- When enabled, `forexfactory_html` is appended as last resort.

## Policy

- Provider chain determines data source priority only.
- It does not authorize trading actions.
- Dashboard and execution consume derived advisory data without strategy overrides.
