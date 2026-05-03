#!/usr/bin/env python3
"""
Apply all FlareSolverr stealth patches to the Chromium source tree.
Run from /chromium/src:  python3 /chromium/patches/apply.py

Uses string replacement so patches survive line-number churn.
On failure, prints the relevant section of the target file so the
search string can be fixed without a full re-sync.
"""

import re
import sys
import pathlib

ERRORS = 0


def _ctx(content: str, pattern: str, radius: int = 20) -> str:
    """Return up to `radius` lines of context around `pattern` in `content`."""
    lines = content.splitlines()
    # Find best matching line index
    best = -1
    best_score = 0
    for i, line in enumerate(lines):
        words = [w for w in re.split(r"\W+", pattern.lower()) if len(w) > 3]
        score = sum(1 for w in words if w in line.lower())
        if score > best_score:
            best_score, best = score, i
    if best < 0:
        best = 0
    lo = max(0, best - radius // 2)
    hi = min(len(lines), best + radius // 2)
    numbered = [f"{lo + i + 1:5}: {line}" for i, line in enumerate(lines[lo:hi])]
    return "\n".join(numbered)


def patch(rel_path: str, old: str, new: str, description: str, fallbacks: "list[str] | None" = None) -> None:
    global ERRORS
    p = pathlib.Path(rel_path)
    if not p.exists():
        print(f"\nERROR [{description}]: file not found: {rel_path}", file=sys.stderr)
        ERRORS += 1
        return

    content = p.read_text()
    for candidate in [old] + (fallbacks or []):
        if candidate in content:
            p.write_text(content.replace(candidate, new, 1))
            print(f"  OK  {rel_path}  ({description})")
            return

    print(f"\nERROR [{description}]: target string not found in {rel_path}", file=sys.stderr)
    print(f"  Searched for: {old[:120]!r}", file=sys.stderr)
    print("  Nearest context in file:", file=sys.stderr)
    for line in _ctx(content, old).splitlines():
        print(f"    {line}", file=sys.stderr)
    ERRORS += 1


def add_include(rel_path: str, new_include: str, after_patterns: "list[str] | None" = None) -> None:
    """Insert new_include if not already present.

    Tries each string in after_patterns as an insertion anchor.
    Falls back to inserting before the first #include "third_party/blink/ line,
    then before the first #include " line, in that order.
    """
    global ERRORS
    p = pathlib.Path(rel_path)
    if not p.exists():
        print(f"\nERROR [add_include]: file not found: {rel_path}", file=sys.stderr)
        ERRORS += 1
        return

    content = p.read_text()

    # Already present?
    if new_include in content:
        print(f"  SKIP {rel_path}  ({new_include!r} already present)")
        return

    # Try explicit anchors first
    for anchor in after_patterns or []:
        if anchor in content:
            content = content.replace(anchor, anchor + "\n" + new_include, 1)
            p.write_text(content)
            print(f"  OK  {rel_path}  (inserted {new_include!r})")
            return

    # Fallback 1: before first #include "third_party/blink/
    m = re.search(r'^(#include "third_party/blink/)', content, re.MULTILINE)
    if m:
        content = content[: m.start()] + new_include + "\n" + content[m.start() :]
        p.write_text(content)
        print(f"  OK  {rel_path}  (inserted {new_include!r} before third_party/blink includes)")
        return

    # Fallback 2: after the last #include "base/ line
    last_base = None
    for m in re.finditer(r'^#include "base/[^\n]+', content, re.MULTILINE):
        last_base = m

    if last_base:
        end = last_base.end()
        content = content[:end] + "\n" + new_include + content[end:]
        p.write_text(content)
        print(f"  OK  {rel_path}  (inserted {new_include!r} after last base include)")
        return

    print(f"\nERROR [add_include]: no insertion point found in {rel_path}", file=sys.stderr)
    print("  First 30 lines:", file=sys.stderr)
    for line in content.splitlines()[:30]:
        print(f"    {line}", file=sys.stderr)
    ERRORS += 1


# ──────────────────────────────────────────────────────────────────────────────
# Patch 1: isTrusted=true for CDP synthetic events
# In Chrome 112+ isTrusted() is an inline function in event.h, not event.cc.
# ──────────────────────────────────────────────────────────────────────────────
print("Patch 1: --enable-trusted-synthetic-events")

add_include(
    "third_party/blink/renderer/core/dom/events/event.h",
    '#include "base/command_line.h"',
    after_patterns=[
        '#include "base/check_op.h"',
        '#include "base/check.h"',
        '#include "base/time/time.h"',
    ],
)

patch(
    "third_party/blink/renderer/core/dom/events/event.h",
    "bool isTrusted() const { return is_trusted_; }",
    (
        "bool isTrusted() const {\n"
        "    if (base::CommandLine::ForCurrentProcess()->HasSwitch(\n"
        '            "enable-trusted-synthetic-events")) {\n'
        "      return true;\n"
        "    }\n"
        "    return is_trusted_;\n"
        "  }"
    ),
    "force isTrusted=true when flag is set",
    fallbacks=[
        # Some builds define it as a two-liner
        "bool isTrusted() const {\n  return is_trusted_;\n}",
        # Older field name
        "bool isTrusted() const { return trusted_; }",
        "bool isTrusted() const {\n  return trusted_;\n}",
    ],
)

# ──────────────────────────────────────────────────────────────────────────────
# Patch 2: navigator.webdriver → undefined (IDL boolean? + C++ std::nullopt)
# Chrome 112+: moved to core/frame/navigator_automation_information.idl +
#              navigator.cc (was in modules/navigatorcontrolled/ before).
# ──────────────────────────────────────────────────────────────────────────────
print("Patch 2: navigator.webdriver → undefined")

# Chrome 112+: navigator_automation_information.idl in core/frame/
patch(
    "third_party/blink/renderer/core/frame/navigator_automation_information.idl",
    "    readonly attribute boolean webdriver;",
    "    readonly attribute boolean? webdriver;",
    "nullable boolean in IDL",
    fallbacks=[
        # Older Chrome: modules/navigatorcontrolled/
        "readonly attribute boolean webdriver;",
    ],
)

add_include(
    "third_party/blink/renderer/core/frame/navigator.h",
    "#include <optional>",
    after_patterns=[
        '#include "third_party/blink/renderer/platform/supplementable.h"',
        '#include "third_party/blink/renderer/platform/wtf/forward.h"',
        '#include "third_party/blink/renderer/core/execution_context/navigator_base.h"',
    ],
)

patch(
    "third_party/blink/renderer/core/frame/navigator.h",
    "  bool webdriver() const;",
    "  std::optional<bool> webdriver() const;",
    "update header declaration",
    fallbacks=[
        # Older Chrome used navigatorcontrolled module
        "third_party/blink/renderer/modules/navigatorcontrolled/navigator_controlled.h",
    ],
)

add_include(
    "third_party/blink/renderer/core/frame/navigator.cc",
    "#include <optional>",
    after_patterns=[
        '#include "third_party/blink/renderer/core/frame/navigator.h"',
    ],
)

patch(
    "third_party/blink/renderer/core/frame/navigator.cc",
    "bool Navigator::webdriver() const {\n"
    "  if (RuntimeEnabledFeatures::AutomationControlledEnabled())\n"
    "    return true;\n"
    "\n"
    "  bool automation_enabled = false;\n"
    "  probe::ApplyAutomationOverride(GetExecutionContext(), automation_enabled);\n"
    "  return automation_enabled;\n"
    "}",
    "std::optional<bool> Navigator::webdriver() const {\n  return std::nullopt;\n}",
    "return nullopt",
    fallbacks=[
        # Older Chrome: navigatorcontrolled module
        "bool NavigatorControlled::webdriver() const {\n  return true;\n}",
    ],
)

# ──────────────────────────────────────────────────────────────────────────────
# Patch 3: WebGL vendor/renderer command-line override
# Chrome 112+ uses WebGLDebugRendererInfo enum values instead of GL_UNMASKED_*.
# ──────────────────────────────────────────────────────────────────────────────
print("Patch 3: --webgl-unmasked-vendor / --webgl-unmasked-renderer")

add_include(
    "third_party/blink/renderer/modules/webgl/webgl_rendering_context_base.cc",
    '#include "base/command_line.h"',
    after_patterns=[
        '#include "base/feature_list.h"',
        '#include "base/notimplemented.h"',
        '#include "base/trace_event/trace_event.h"',
        '#include "base/atomic_sequence_num.h"',
        '#include "base/check.h"',
        '#include "base/check_op.h"',
        '#include "base/notreached.h"',
    ],
)

# Chrome 112+: UNMASKED uses WebGLDebugRendererInfo enum + ContextGL()->GetString()
patch(
    "third_party/blink/renderer/modules/webgl/webgl_rendering_context_base.cc",
    "    case WebGLDebugRendererInfo::kUnmaskedRendererWebgl:\n"
    "      if (ExtensionEnabled(kWebGLDebugRendererInfoName)) {\n"
    "        return WebGLAny(script_state,\n"
    "                        String(ContextGL()->GetString(GL_RENDERER)));\n"
    "      }\n"
    "      SynthesizeGLError(\n"
    '          GL_INVALID_ENUM, "getParameter",\n'
    '          "invalid parameter name, WEBGL_debug_renderer_info not enabled");\n'
    "      return ScriptValue::CreateNull(script_state->GetIsolate());\n"
    "    case WebGLDebugRendererInfo::kUnmaskedVendorWebgl:\n"
    "      if (ExtensionEnabled(kWebGLDebugRendererInfoName)) {\n"
    "        return WebGLAny(script_state,\n"
    "                        String(ContextGL()->GetString(GL_VENDOR)));\n"
    "      }\n"
    "      SynthesizeGLError(\n"
    '          GL_INVALID_ENUM, "getParameter",\n'
    '          "invalid parameter name, WEBGL_debug_renderer_info not enabled");\n'
    "      return ScriptValue::CreateNull(script_state->GetIsolate());",
    (
        "    case WebGLDebugRendererInfo::kUnmaskedRendererWebgl:\n"
        "      if (ExtensionEnabled(kWebGLDebugRendererInfoName)) {\n"
        '        if (base::CommandLine::ForCurrentProcess()->HasSwitch("webgl-unmasked-renderer")) {\n'
        "          return WebGLAny(script_state, String(base::CommandLine::ForCurrentProcess()\n"
        '                                                   ->GetSwitchValueASCII("webgl-unmasked-renderer")));\n'
        "        }\n"
        "        return WebGLAny(script_state,\n"
        "                        String(ContextGL()->GetString(GL_RENDERER)));\n"
        "      }\n"
        "      SynthesizeGLError(\n"
        '          GL_INVALID_ENUM, "getParameter",\n'
        '          "invalid parameter name, WEBGL_debug_renderer_info not enabled");\n'
        "      return ScriptValue::CreateNull(script_state->GetIsolate());\n"
        "    case WebGLDebugRendererInfo::kUnmaskedVendorWebgl:\n"
        "      if (ExtensionEnabled(kWebGLDebugRendererInfoName)) {\n"
        '        if (base::CommandLine::ForCurrentProcess()->HasSwitch("webgl-unmasked-vendor")) {\n'
        "          return WebGLAny(script_state, String(base::CommandLine::ForCurrentProcess()\n"
        '                                                   ->GetSwitchValueASCII("webgl-unmasked-vendor")));\n'
        "        }\n"
        "        return WebGLAny(script_state,\n"
        "                        String(ContextGL()->GetString(GL_VENDOR)));\n"
        "      }\n"
        "      SynthesizeGLError(\n"
        '          GL_INVALID_ENUM, "getParameter",\n'
        '          "invalid parameter name, WEBGL_debug_renderer_info not enabled");\n'
        "      return ScriptValue::CreateNull(script_state->GetIsolate());"
    ),
    "intercept UNMASKED_VENDOR/RENDERER (Chrome 112+ enum style)",
    fallbacks=[
        # Older Chrome uses GL_UNMASKED_* integer constants directly
        "    case GL_UNMASKED_VENDOR_WEBGL:\n"
        '      return WebGLAny(script_state, String("WebKit"));\n'
        "    case GL_UNMASKED_RENDERER_WEBGL:\n"
        '      return WebGLAny(script_state, String("WebKit"));',
    ],
)

# ──────────────────────────────────────────────────────────────────────────────
# Patch 4: --preload-script flag (document_start injection via V8)
# Chrome 112+: AddScriptToEvaluateOnNewDocument was removed from WebContents.
# Hook into RenderFrameImpl::DidCreateScriptContext — runs for every new JS
# context before any page scripts, using raw V8 (no Blink deps needed).
# ──────────────────────────────────────────────────────────────────────────────
print("Patch 4: --preload-script flag")

add_include(
    "content/renderer/render_frame_impl.cc",
    '#include "base/files/file_util.h"',
    after_patterns=[
        '#include "base/command_line.h"',
        '#include "base/check_deref.h"',
        '#include "base/byte_count.h"',
    ],
)

_PRELOAD_INJECTION = (
    "  // --preload-script: evaluate JS file at document_start in every new context.\n"
    "  if (world_id == ISOLATED_WORLD_ID_GLOBAL) {\n"
    "    static std::string* preload_script_content = new std::string();\n"
    "    static bool preload_script_loaded = false;\n"
    "    if (!preload_script_loaded) {\n"
    "      preload_script_loaded = true;\n"
    "      base::CommandLine* cmd = base::CommandLine::ForCurrentProcess();\n"
    '      if (cmd->HasSwitch("preload-script")) {\n'
    "        base::ReadFileToString(\n"
    '            cmd->GetSwitchValuePath("preload-script"),\n'
    "            preload_script_content);\n"
    "      }\n"
    "    }\n"
    "    if (!preload_script_content->empty()) {\n"
    "      v8::Isolate* isolate = v8::Isolate::GetCurrent();\n"
    "      v8::Local<v8::String> source =\n"
    "          v8::String::NewFromUtf8(isolate, preload_script_content->c_str(),\n"
    "                                  v8::NewStringType::kNormal)\n"
    "              .ToLocalChecked();\n"
    "      v8::Local<v8::Script> script;\n"
    "      if (v8::Script::Compile(context, source).ToLocal(&script)) {\n"
    "        v8::Local<v8::Value> result;\n"
    "        (void)script->Run(context).ToLocal(&result);\n"
    "      }\n"
    "    }\n"
    "  }\n"
)

patch(
    "content/renderer/render_frame_impl.cc",
    "  for (auto& observer : observers_)\n    observer.DidCreateScriptContext(context, world_id);\n}",
    _PRELOAD_INJECTION + "  for (auto& observer : observers_)\n    observer.DidCreateScriptContext(context, world_id);\n}",
    "inject preload script at context creation",
)

# ──────────────────────────────────────────────────────────────────────────────
# Patch 5: Inject preload script into DedicatedWorkerGlobalScope at C++ level
# Chrome 112+: hook before EvaluateClassicScript() in DidFetchClassicScript.
# ──────────────────────────────────────────────────────────────────────────────
print("Patch 5: worker prelude injection")

add_include(
    "third_party/blink/renderer/core/workers/dedicated_worker_global_scope.cc",
    '#include "base/command_line.h"',
    after_patterns=[
        '#include "base/types/pass_key.h"',
        '#include "base/metrics/histogram_macros.h"',
        '#include "third_party/blink/renderer/core/workers/dedicated_worker_global_scope.h"',
        '#include "third_party/blink/renderer/bindings/core/v8/serialization/serialized_script_value.h"',
    ],
)

add_include(
    "third_party/blink/renderer/core/workers/dedicated_worker_global_scope.cc",
    '#include "base/files/file_util.h"',
    after_patterns=[
        '#include "base/command_line.h"',
    ],
)

add_include(
    "third_party/blink/renderer/core/workers/dedicated_worker_global_scope.cc",
    '#include "third_party/blink/renderer/core/script/classic_script.h"',
    after_patterns=[
        '#include "third_party/blink/renderer/bindings/core/v8/worker_or_worklet_script_controller.h"',
        '#include "third_party/blink/renderer/core/frame/local_frame.h"',
    ],
)

_WORKER_PRELOAD = (
    "  // --preload-script: evaluate preload content before any user worker scripts.\n"
    "  {\n"
    "    static std::string* preload_content = new std::string();\n"
    "    static bool preload_loaded = false;\n"
    "    if (!preload_loaded) {\n"
    "      preload_loaded = true;\n"
    "      base::CommandLine* cmd = base::CommandLine::ForCurrentProcess();\n"
    '      if (cmd->HasSwitch("preload-script")) {\n'
    '        base::FilePath path = cmd->GetSwitchValuePath("preload-script");\n'
    "        if (!base::ReadFileToString(path, preload_content))\n"
    "          preload_content->clear();\n"
    "      }\n"
    "    }\n"
    "    if (!preload_content->empty()) {\n"
    "      ClassicScript* script = ClassicScript::Create(\n"
    "          String::FromUtf8(*preload_content),\n"
    '          KURL("about:preload-script"),\n'
    "          KURL(),\n"
    "          ScriptFetchOptions(),\n"
    "          ScriptSourceLocationType::kInternal,\n"
    "          SanitizeScriptErrors::kDoNotSanitize);\n"
    "      std::ignore = script->RunScriptOnScriptStateAndReturnValue(\n"
    "          ScriptController()->GetScriptState());\n"
    "    }\n"
    "  }\n"
)

# Chrome 112+: inject before EvaluateClassicScript() in DidFetchClassicScript
patch(
    "third_party/blink/renderer/core/workers/dedicated_worker_global_scope.cc",
    "  EvaluateClassicScript(\n"
    "      classic_script_loader->ResponseURL(), classic_script_loader->SourceText(),\n"
    "      classic_script_loader->ReleaseCachedMetadata(), stack_id);",
    _WORKER_PRELOAD + "  EvaluateClassicScript(\n"
    "      classic_script_loader->ResponseURL(), classic_script_loader->SourceText(),\n"
    "      classic_script_loader->ReleaseCachedMetadata(), stack_id);",
    "evaluate preload script before user code",
    fallbacks=[
        # Older hook point: before WorkerGlobalScope::Initialize call
        "  WorkerGlobalScope::Initialize(user_agent,",
    ],
)

# ──────────────────────────────────────────────────────────────────────────────

if ERRORS:
    print(f"\n{ERRORS} patch(es) failed — see errors above.", file=sys.stderr)
    sys.exit(1)

print("\nAll patches applied successfully.")
