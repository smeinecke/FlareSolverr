## Feature Request

Add support for injecting custom JavaScript into pages and executing JS as part of the Action system.

## Security Control

Master switch via environment variable:
- `JS_INJECTION_ENABLED` (default: `false`) - Must be explicitly enabled

## Request Parameters

New optional fields on GET/POST requests:

| Field | Type | Description |
|-------|------|-------------|
| `jsInjection` | string | JavaScript code to inject |
| `jsInjectionPoint` | string | When to inject: `document_start`, `document_end`, `document_idle` |

## Injection Points

- `document_start`: Before page load (via CDP `Page.addScriptToEvaluateOnNewDocument`)
- `document_end`: After DOM ready, before challenge detection  
- `document_idle`: After challenge resolution, before result capture (default)

## New Action Type

`execute_js` - Execute JS and optionally return the result:

```json
{"type": "execute_js", "code": "return document.title", "returnResult": true}
```

## Example Request

```json
{
  "cmd": "request.get",
  "url": "https://example.com",
  "jsInjection": "window.myCustomVar = 'foo';",
  "jsInjectionPoint": "document_start",
  "actions": [
    {"type": "execute_js", "code": "return window.myCustomVar", "returnResult": true}
  ]
}
```
