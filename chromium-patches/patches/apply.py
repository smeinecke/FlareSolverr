#!/usr/bin/env python3
"""
Apply all FlareSolverr stealth patches to the Chromium source tree.
Run from /chromium/src:  python3 /chromium/patches/apply.py

Uses string replacement instead of unified-diff format so the patches
survive line-number churn across Chromium versions.  Any patch that
cannot find its target string exits with a non-zero code and prints
the file path so the build fails loudly.
"""
import sys
import pathlib


def patch(rel_path: str, old: str, new: str, description: str = "") -> None:
    p = pathlib.Path(rel_path)
    if not p.exists():
        print(f"ERROR [{description}]: file not found: {rel_path}", file=sys.stderr)
        sys.exit(1)
    content = p.read_text()
    if old not in content:
        print(f"ERROR [{description}]: target string not found in {rel_path}", file=sys.stderr)
        print(f"  Looking for: {old[:80]!r}", file=sys.stderr)
        sys.exit(1)
    p.write_text(content.replace(old, new, 1))
    print(f"  OK  {rel_path}" + (f" — {description}" if description else ""))


# ──────────────────────────────────────────────────────────────────────────────
# Patch 1: isTrusted=true for CDP synthetic events
# ──────────────────────────────────────────────────────────────────────────────
print("Patch 1: --enable-trusted-synthetic-events")

patch(
    "third_party/blink/renderer/core/dom/events/event.cc",
    '#include "base/check.h"',
    '#include "base/check.h"\n#include "base/command_line.h"',
    "add command_line.h include",
)

patch(
    "third_party/blink/renderer/core/dom/events/event.cc",
    "bool Event::isTrusted() const {\n  return trusted_;\n}",
    (
        "bool Event::isTrusted() const {\n"
        '  if (base::CommandLine::ForCurrentProcess()->HasSwitch(\n'
        '          "enable-trusted-synthetic-events")) {\n'
        "    return true;\n"
        "  }\n"
        "  return trusted_;\n"
        "}"
    ),
    "force isTrusted=true when flag is set",
)

# ──────────────────────────────────────────────────────────────────────────────
# Patch 2: CDP mouse screenX/Y window-bounds offset
# ──────────────────────────────────────────────────────────────────────────────
print("Patch 2: CDP mouse screenX/Y offset")

patch(
    "content/browser/devtools/protocol/input_handler.cc",
    "  gfx::PointF screen_point(x, y);\n  if (web_view) {",
    (
        "  gfx::PointF screen_point(x, y);\n"
        "  gfx::Rect window_bounds = web_contents_->GetContainerBounds();\n"
        "  screen_point.Offset(window_bounds.x(), window_bounds.y());\n"
        "  if (web_view) {"
    ),
    "add window bounds offset",
)

# ──────────────────────────────────────────────────────────────────────────────
# Patch 3: navigator.webdriver → undefined (IDL boolean? + C++ std::nullopt)
# ──────────────────────────────────────────────────────────────────────────────
print("Patch 3: navigator.webdriver → undefined")

patch(
    "third_party/blink/renderer/modules/navigatorcontrolled/navigator_controlled.idl",
    "readonly attribute boolean webdriver;",
    "readonly attribute boolean? webdriver;",
    "nullable boolean in IDL",
)

patch(
    "third_party/blink/renderer/modules/navigatorcontrolled/navigator_controlled.h",
    '#include "third_party/blink/renderer/core/frame/navigator.h"',
    '#include <optional>\n#include "third_party/blink/renderer/core/frame/navigator.h"',
    "add <optional> include",
)

patch(
    "third_party/blink/renderer/modules/navigatorcontrolled/navigator_controlled.h",
    "  bool webdriver() const;",
    "  std::optional<bool> webdriver() const;",
    "update declaration",
)

patch(
    "third_party/blink/renderer/modules/navigatorcontrolled/navigator_controlled.cc",
    "bool NavigatorControlled::webdriver() const {\n  return true;\n}",
    "std::optional<bool> NavigatorControlled::webdriver() const {\n  return std::nullopt;\n}",
    "return nullopt",
)

# ──────────────────────────────────────────────────────────────────────────────
# Patch 4: WebGL vendor/renderer command-line override
# ──────────────────────────────────────────────────────────────────────────────
print("Patch 4: --webgl-unmasked-vendor / --webgl-unmasked-renderer")

patch(
    "third_party/blink/renderer/modules/webgl/webgl_rendering_context_base.cc",
    '#include "base/atomic_sequence_num.h"',
    '#include "base/atomic_sequence_num.h"\n#include "base/command_line.h"',
    "add command_line.h include",
)

patch(
    "third_party/blink/renderer/modules/webgl/webgl_rendering_context_base.cc",
    "    case GL_UNMASKED_VENDOR_WEBGL:\n"
    "      return WebGLAny(script_state, String(\"WebKit\"));\n"
    "    case GL_UNMASKED_RENDERER_WEBGL:\n"
    "      return WebGLAny(script_state, String(\"WebKit\"));",
    (
        "    case GL_UNMASKED_VENDOR_WEBGL:\n"
        '      if (base::CommandLine::ForCurrentProcess()->HasSwitch("webgl-unmasked-vendor")) {\n'
        "        return WebGLAny(script_state,\n"
        '            base::CommandLine::ForCurrentProcess()->GetSwitchValueASCII("webgl-unmasked-vendor"));\n'
        "      }\n"
        '      return WebGLAny(script_state, String("WebKit"));\n'
        "    case GL_UNMASKED_RENDERER_WEBGL:\n"
        '      if (base::CommandLine::ForCurrentProcess()->HasSwitch("webgl-unmasked-renderer")) {\n'
        "        return WebGLAny(script_state,\n"
        '            base::CommandLine::ForCurrentProcess()->GetSwitchValueASCII("webgl-unmasked-renderer"));\n'
        "      }\n"
        '      return WebGLAny(script_state, String("WebKit"));'
    ),
    "intercept UNMASKED_VENDOR/RENDERER",
)

# ──────────────────────────────────────────────────────────────────────────────
# Patch 5: --preload-script flag (document_start injection per WebContents)
# ──────────────────────────────────────────────────────────────────────────────
print("Patch 5: --preload-script flag")

patch(
    "content/browser/web_contents/web_contents_impl.cc",
    '#include "base/check.h"',
    '#include "base/check.h"\n#include "base/command_line.h"\n#include "base/files/file_util.h"',
    "add command_line.h + file_util.h includes",
)

# Hook into the end of WebContentsImpl::Init() — find the closing of the
# Init signature area and insert after existing setup.  The string below is
# stable across recent Chromium versions; adjust if the build fails here.
patch(
    "content/browser/web_contents/web_contents_impl.cc",
    "void WebContentsImpl::Init(const WebContents::CreateParams& params,\n"
    "                           blink::FramePolicy frame_policy) {",
    (
        "void WebContentsImpl::Init(const WebContents::CreateParams& params,\n"
        "                           blink::FramePolicy frame_policy) {\n"
        "  // --preload-script: register a JS file to run at document_start in every\n"
        "  // new document context for this WebContents, without a CDP round-trip.\n"
        "  {\n"
        "    static std::string preload_script_content;\n"
        "    static bool preload_script_loaded = false;\n"
        "    if (!preload_script_loaded) {\n"
        "      preload_script_loaded = true;\n"
        "      base::CommandLine* cmd = base::CommandLine::ForCurrentProcess();\n"
        '      if (cmd->HasSwitch("preload-script")) {\n'
        "        base::ReadFileToString(\n"
        '            cmd->GetSwitchValuePath("preload-script"), &preload_script_content);\n'
        "      }\n"
        "    }\n"
        "    if (!preload_script_content.empty()) {\n"
        "      AddScriptToEvaluateOnNewDocument(preload_script_content, std::nullopt);\n"
        "    }\n"
        "  }"
    ),
    "register preload script per WebContents",
)

# ──────────────────────────────────────────────────────────────────────────────
# Patch 6: Inject preload script into DedicatedWorkerGlobalScope at C++ level
# ──────────────────────────────────────────────────────────────────────────────
print("Patch 6: worker prelude injection")

patch(
    "third_party/blink/renderer/core/workers/dedicated_worker_global_scope.cc",
    '#include "third_party/blink/renderer/core/workers/dedicated_worker_global_scope.h"',
    (
        '#include "third_party/blink/renderer/core/workers/dedicated_worker_global_scope.h"\n'
        '#include "base/command_line.h"\n'
        '#include "base/files/file_util.h"'
    ),
    "add command_line.h + file_util.h includes",
)

# Insert at the end of DedicatedWorkerGlobalScope::Initialize() by finding its
# closing sequence just before WorkerGlobalScope::Initialize call.
patch(
    "third_party/blink/renderer/core/workers/dedicated_worker_global_scope.cc",
    "  WorkerGlobalScope::Initialize(user_agent,",
    (
        "  // --preload-script: evaluate preload content before any user worker scripts.\n"
        "  {\n"
        "    static std::string preload_content;\n"
        "    static bool preload_loaded = false;\n"
        "    if (!preload_loaded) {\n"
        "      preload_loaded = true;\n"
        "      base::CommandLine* cmd = base::CommandLine::ForCurrentProcess();\n"
        '      if (cmd->HasSwitch("preload-script")) {\n'
        "        base::FilePath path = cmd->GetSwitchValuePath(\"preload-script\");\n"
        "        if (!base::ReadFileToString(path, &preload_content))\n"
        "          preload_content.clear();\n"
        "      }\n"
        "    }\n"
        "    if (!preload_content.empty()) {\n"
        "      ClassicScript* script = ClassicScript::Create(\n"
        "          String::FromUTF8(preload_content),\n"
        '          KURL("about:preload-script"),\n'
        "          KURL(),\n"
        "          ScriptFetchOptions(),\n"
        "          ScriptSourceLocationType::kInternal,\n"
        "          SanitizeScriptErrors::kDoNotSanitize);\n"
        "      script->RunScriptOnScriptState(GetScriptController()->GetScriptState());\n"
        "    }\n"
        "  }\n"
        "  WorkerGlobalScope::Initialize(user_agent,"
    ),
    "evaluate preload script before user code",
)

# ──────────────────────────────────────────────────────────────────────────────
# Patch 7: Remove HeadlessChrome UA token
# ──────────────────────────────────────────────────────────────────────────────
print("Patch 7: remove HeadlessChrome UA token")

patch(
    "chrome/browser/headless/headless_mode_util.cc",
    'content::SetBrowserClientUserAgentProduct("HeadlessChrome");',
    "// Omitted: SetBrowserClientUserAgentProduct(\"HeadlessChrome\").\n"
    "  // Presenting as regular Chrome avoids the most direct bot-detection signal.",
    "suppress HeadlessChrome UA token",
)

print("\nAll patches applied successfully.")
