#!/usr/bin/env python3
"""
Apply Chromium C++ patches for FlareSolverr stealth mode.

Run from /chromium/src:  python3 /chromium/patches/apply.py

Uses string replacement so patches survive line-number churn.
On failure, prints the relevant section of the target file so the
search string can be fixed without a full re-sync.
"""

import argparse
import pathlib
import re
import sys


class PatchApplier:
    """Applies Chromium C++ patches and tracks touched files."""

    def __init__(self) -> None:
        self.errors = 0
        self.dry_run = False
        self.list_files_only = False
        self.patched_files: list[str] = []

    def _ctx(self, content: str, pattern: str, radius: int = 20) -> str:
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

    def patch(self, rel_path: str, old: str, new: str, description: str, fallbacks: "list[str] | None" = None) -> None:
        if rel_path not in self.patched_files:
            self.patched_files.append(rel_path)
        if self.list_files_only:
            return

        p = pathlib.Path(rel_path)
        if not p.exists():
            print(f"\nERROR [{description}]: file not found: {rel_path}", file=sys.stderr)
            self.errors += 1
            return

        content = p.read_text()
        # If the replacement is already present, the patch was applied previously
        if new in content:
            print(f"  SKIP  {rel_path}  ({description} – already patched)")
            return

        for candidate in [old] + (fallbacks or []):
            if candidate in content:
                if self.dry_run:
                    print(f"  WOULD_PATCH  {rel_path}  ({description})")
                else:
                    p.write_text(content.replace(candidate, new, 1))
                    print(f"  OK  {rel_path}  ({description})")
                return

        print(f"\nERROR [{description}]: target string not found in {rel_path}", file=sys.stderr)
        print(f"  Searched for: {old[:120]!r}", file=sys.stderr)
        print("  Nearest context in file:", file=sys.stderr)
        for line in self._ctx(content, old).splitlines():
            print(f"    {line}", file=sys.stderr)
        self.errors += 1

    def add_include(self, rel_path: str, new_include: str, after_patterns: "list[str] | None" = None) -> None:
        """Insert new_include if not already present.

        Tries each string in after_patterns as an insertion anchor.
        Falls back to inserting before the first #include "third_party/blink/ line,
        then after the last #include "base/ line, in that order.
        """
        if rel_path not in self.patched_files:
            self.patched_files.append(rel_path)
        if self.list_files_only:
            return

        p = pathlib.Path(rel_path)
        if not p.exists():
            print(f"\nERROR [add_include]: file not found: {rel_path}", file=sys.stderr)
            self.errors += 1
            return

        content = p.read_text()

        # Already present?
        if new_include in content:
            print(f"  SKIP {rel_path}  ({new_include!r} already present)")
            return

        # Try explicit anchors first
        for anchor in after_patterns or []:
            if anchor in content:
                if self.dry_run:
                    print(f"  WOULD_INSERT  {rel_path}  ({new_include!r})")
                else:
                    content = content.replace(anchor, anchor + "\n" + new_include, 1)
                    p.write_text(content)
                    print(f"  OK  {rel_path}  (inserted {new_include!r})")
                return

        # Fallback 1: before first #include "third_party/blink/
        m = re.search(r'^(#include "third_party/blink/)', content, re.MULTILINE)
        if m:
            if self.dry_run:
                print(f"  WOULD_INSERT  {rel_path}  ({new_include!r} before third_party/blink includes)")
            else:
                content = content[: m.start()] + new_include + "\n" + content[m.start() :]
                p.write_text(content)
                print(f"  OK  {rel_path}  (inserted {new_include!r} before third_party/blink includes)")
            return

        # Fallback 2: after the last #include "base/ line
        last_base = None
        for m in re.finditer(r'^#include "base/[^\n]+', content, re.MULTILINE):
            last_base = m

        if last_base:
            if self.dry_run:
                print(f"  WOULD_INSERT  {rel_path}  ({new_include!r} after last base include)")
            else:
                end = last_base.end()
                content = content[:end] + "\n" + new_include + content[end:]
                p.write_text(content)
                print(f"  OK  {rel_path}  (inserted {new_include!r} after last base include)")
            return

        print(f"\nERROR [add_include]: no insertion point found in {rel_path}", file=sys.stderr)
        print("  First 30 lines:", file=sys.stderr)
        for line in content.splitlines()[:30]:
            print(f"    {line}", file=sys.stderr)
        self.errors += 1

    def run_patches(self) -> None:
        # ──────────────────────────────────────────────────────────────────────────────
        # Patch 1: isTrusted=true for CDP synthetic events
        # In Chrome 112+ isTrusted() is an inline function in event.h, not event.cc.
        # ──────────────────────────────────────────────────────────────────────────────
        print("Patch 1: --enable-trusted-synthetic-events")

        self.add_include(
            "third_party/blink/renderer/core/dom/events/event.h",
            '#include "base/command_line.h"',
            after_patterns=[
                '#include "base/check_op.h"',
                '#include "base/check.h"',
                '#include "base/time/time.h"',
            ],
        )

        self.patch(
            "third_party/blink/renderer/core/dom/events/event.h",
            "bool isTrusted() const { return is_trusted_; }",
            (
                "bool isTrusted() const {\n"
                "    // Static cached flag to avoid CommandLine lookup on every call\n"
                "    // (thread-safe in C++11+: static init is guaranteed once)\n"
                "    static const bool force_trusted = []() {\n"
                "      return base::CommandLine::ForCurrentProcess()->HasSwitch(\n"
                '          "enable-trusted-synthetic-events");\n'
                "    }();\n"
                "    if (force_trusted)\n"
                "      return true;\n"
                "    return is_trusted_;\n"
                "  }"
            ),
            "force isTrusted=true when flag is set (cached, thread-safe)",
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
        self.patch(
            "third_party/blink/renderer/core/frame/navigator_automation_information.idl",
            "    readonly attribute boolean webdriver;",
            "    readonly attribute boolean? webdriver;",
            "nullable boolean in IDL",
            fallbacks=[
                # Older Chrome: modules/navigatorcontrolled/
                "readonly attribute boolean webdriver;",
            ],
        )

        self.add_include(
            "third_party/blink/renderer/core/frame/navigator.h",
            "#include <optional>",
            after_patterns=[
                '#include "third_party/blink/renderer/platform/supplementable.h"',
                '#include "third_party/blink/renderer/platform/wtf/forward.h"',
                '#include "third_party/blink/renderer/core/execution_context/navigator_base.h"',
            ],
        )

        self.patch(
            "third_party/blink/renderer/core/frame/navigator.h",
            "  bool webdriver() const;",
            "  std::optional<bool> webdriver() const;",
            "update header declaration",
        )

        self.add_include(
            "third_party/blink/renderer/core/frame/navigator.cc",
            "#include <optional>",
            after_patterns=[
                '#include "third_party/blink/renderer/core/frame/navigator.h"',
            ],
        )

        self.patch(
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

        self.add_include(
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
        self.patch(
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

        # Patch 3b: Forward webgl-unmasked-* switches from browser process to renderer.
        # Chrome's multi-process model does NOT automatically propagate custom switches
        # to renderer processes — they must be explicitly copied in AppendRendererCommandLine
        # (or the equivalent AppendExtraCommandLineSwitches hook).
        # File: content/browser/renderer_host/render_process_host_impl.cc
        print("Patch 3b: forward webgl-unmasked-* switches to renderer processes")

        self.add_include(
            "content/browser/renderer_host/render_process_host_impl.cc",
            '#include "base/command_line.h"',
            after_patterns=[
                '#include "base/check_deref.h"',
                '#include "base/byte_count.h"',
                '#include "base/allocator/partition_allocator/src/partition_alloc/partition_alloc_buildflags.h"',
            ],
        )

        self.patch(
            "content/browser/renderer_host/render_process_host_impl.cc",
            "void RenderProcessHostImpl::AppendRendererCommandLine(\n    base::CommandLine* command_line) {",
            "void RenderProcessHostImpl::AppendRendererCommandLine(\n"
            "    base::CommandLine* command_line) {\n"
            "  // Forward custom stealth switches to renderer processes.\n"
            "  const base::CommandLine& browser_cmd =\n"
            "      *base::CommandLine::ForCurrentProcess();\n"
            '  for (const char* sw : {"webgl-unmasked-vendor", "webgl-unmasked-renderer",\n'
            '                          "preload-script", "enable-trusted-synthetic-events"}) {\n'
            "    if (browser_cmd.HasSwitch(sw))\n"
            "      command_line->AppendSwitchASCII(sw, browser_cmd.GetSwitchValueASCII(sw));\n"
            "  }",
            "forward stealth switches from browser to renderer process command line",
        )

        # ──────────────────────────────────────────────────────────────────────────────
        # Patch 4: --preload-script flag (document_start injection via Blink WebFrame)
        # Hook into RenderFrameImpl::DidCreateDocumentElement — fires AFTER V8 context
        # creation is complete, so it is safe to compile and run scripts.
        # DO NOT use DidCreateScriptContext: that fires DURING V8 context creation while
        # V8 holds internal spinlocks; calling Script::Compile there spins at 97% CPU.
        # ──────────────────────────────────────────────────────────────────────────────
        print("Patch 4: --preload-script flag")

        self.add_include(
            "content/renderer/render_frame_impl.cc",
            '#include "base/files/file_util.h"',
            after_patterns=[
                '#include "base/command_line.h"',
                '#include "base/check_deref.h"',
                '#include "base/byte_count.h"',
            ],
        )

        self.add_include(
            "content/renderer/render_frame_impl.cc",
            '#include "third_party/blink/public/web/web_script_source.h"',
            after_patterns=[
                '#include "base/files/file_util.h"',
                '#include "base/command_line.h"',
            ],
        )

        _PRELOAD_INJECTION = (
            "  // --preload-script: evaluate JS file before any page scripts.\n"
            "  // Safe here because DidCreateDocumentElement fires after V8 context init.\n"
            "  {\n"
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
            "    if (!preload_script_content->empty() && GetWebFrame()) {\n"
            "      GetWebFrame()->ExecuteScript(\n"
            "          blink::WebScriptSource(\n"
            "              blink::WebString::FromUTF8(*preload_script_content)));\n"
            "    }\n"
            "  }\n"
        )

        self.patch(
            "content/renderer/render_frame_impl.cc",
            "  for (auto& observer : observers_)\n    observer.DidCreateDocumentElement();\n}",
            _PRELOAD_INJECTION + "  for (auto& observer : observers_)\n    observer.DidCreateDocumentElement();\n}",
            "inject preload script at DidCreateDocumentElement (safe, after V8 init)",
        )

        # ──────────────────────────────────────────────────────────────────────────────
        # Patch 5: Inject preload script into DedicatedWorkerGlobalScope at C++ level
        # Chrome 112+: hook before EvaluateClassicScript() in DidFetchClassicScript.
        # ──────────────────────────────────────────────────────────────────────────────
        print("Patch 5: worker prelude injection")

        self.add_include(
            "third_party/blink/renderer/core/workers/dedicated_worker_global_scope.cc",
            '#include "base/command_line.h"',
            after_patterns=[
                '#include "base/types/pass_key.h"',
                '#include "base/metrics/histogram_macros.h"',
                '#include "third_party/blink/renderer/core/workers/dedicated_worker_global_scope.h"',
                '#include "third_party/blink/renderer/bindings/core/v8/serialization/serialized_script_value.h"',
            ],
        )

        self.add_include(
            "third_party/blink/renderer/core/workers/dedicated_worker_global_scope.cc",
            '#include "base/files/file_util.h"',
            after_patterns=[
                '#include "base/command_line.h"',
            ],
        )

        self.add_include(
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
        self.patch(
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
        # Patch 6: Remove "HeadlessChrome" product name token from UA string and
        # userAgentData brand lists — replace with plain "Chrome" so headless mode
        # is indistinguishable from a normal browser UA.
        # File: headless/lib/browser/headless_browser_impl.cc
        # ──────────────────────────────────────────────────────────────────────────────
        print("Patch 6: HeadlessChrome → Chrome in UA product name")

        self.patch(
            "headless/lib/browser/headless_browser_impl.cc",
            'const char kHeadlessProductName[] = "HeadlessChrome";',
            'const char kHeadlessProductName[] = "Chrome";',
            "rename HeadlessChrome product token to Chrome",
        )

        # ──────────────────────────────────────────────────────────────────────────────
        # Patch 7: VisualViewport width/height to match innerWidth/innerHeight
        # Prevents detection via visualViewport vs innerWidth/innerHeight mismatch.
        # The width()/height() methods return visible_size_; override to return
        # innerWidth/innerHeight when stealth flag is set.
        # File: third_party/blink/renderer/core/frame/visual_viewport.cc
        # ──────────────────────────────────────────────────────────────────────────────
        print("Patch 7: visualViewport width/height → innerWidth/innerHeight")

        self.add_include(
            "third_party/blink/renderer/core/frame/visual_viewport.cc",
            '#include "base/command_line.h"',
            after_patterns=[
                '#include "base/check_op.h"',
                '#include "base/notreached.h"',
            ],
        )

        self.patch(
            "third_party/blink/renderer/core/frame/visual_viewport.cc",
            "double VisualViewport::Width() const {\n"
            "  DCHECK(IsActiveViewport());\n"
            "  if (Document* document = LocalMainFrame().GetDocument())\n"
            "    document->UpdateStyleAndLayout(DocumentUpdateReason::kJavaScript);\n"
            "  return VisibleWidthCSSPx();\n"
            "}",
            (
                "double VisualViewport::Width() const {\n"
                "  // When stealth flag is set, return the layout viewport width to avoid\n"
                "  // visualViewport vs innerWidth coherence mismatch detection.\n"
                "  // Note: do NOT call window->innerWidth() here — that recurses back into\n"
                "  // VisualViewport::Width() via Page::GetVisualViewport().Width().\n"
                "  static const bool stealth_viewport =\n"
                '      base::CommandLine::ForCurrentProcess()->HasSwitch("stealth-viewport-size");\n'
                "  if (stealth_viewport && LocalMainFrame().View()) {\n"
                "    return LocalMainFrame().View()->GetLayoutSize().width();\n"
                "  }\n"
                "  DCHECK(IsActiveViewport());\n"
                "  if (Document* document = LocalMainFrame().GetDocument())\n"
                "    document->UpdateStyleAndLayout(DocumentUpdateReason::kJavaScript);\n"
                "  return VisibleWidthCSSPx();\n"
                "}"
            ),
            "visualViewport Width() returns layout viewport width with stealth flag",
        )

        self.patch(
            "third_party/blink/renderer/core/frame/visual_viewport.cc",
            "double VisualViewport::Height() const {\n"
            "  DCHECK(IsActiveViewport());\n"
            "  if (Document* document = LocalMainFrame().GetDocument())\n"
            "    document->UpdateStyleAndLayout(DocumentUpdateReason::kJavaScript);\n"
            "  return VisibleHeightCSSPx();\n"
            "}",
            (
                "double VisualViewport::Height() const {\n"
                "  // When stealth flag is set, return the layout viewport height to avoid\n"
                "  // visualViewport vs innerHeight coherence mismatch detection.\n"
                "  // Note: do NOT call window->innerHeight() here — that recurses back into\n"
                "  // VisualViewport::Height() via Page::GetVisualViewport().Height().\n"
                "  static const bool stealth_viewport =\n"
                '      base::CommandLine::ForCurrentProcess()->HasSwitch("stealth-viewport-size");\n'
                "  if (stealth_viewport && LocalMainFrame().View()) {\n"
                "    return LocalMainFrame().View()->GetLayoutSize().height();\n"
                "  }\n"
                "  DCHECK(IsActiveViewport());\n"
                "  if (Document* document = LocalMainFrame().GetDocument())\n"
                "    document->UpdateStyleAndLayout(DocumentUpdateReason::kJavaScript);\n"
                "  return VisibleHeightCSSPx();\n"
                "}"
            ),
            "visualViewport Height() returns layout viewport height with stealth flag",
        )

        # ──────────────────────────────────────────────────────────────────────────────
        # Patch 8: Navigator languages to return non-empty array
        # Headless Chrome returns [] which is detectable. Return ['en-US', 'en'] instead.
        # File: third_party/blink/renderer/core/frame/navigator_language.cc
        # ──────────────────────────────────────────────────────────────────────────────
        print("Patch 8: navigator.languages returns ['en-US', 'en'] instead of []")

        self.add_include(
            "third_party/blink/renderer/core/frame/navigator_language.cc",
            '#include "base/command_line.h"',
            after_patterns=[
                '#include "third_party/blink/renderer/core/frame/navigator_language.h"',
                '#include "third_party/blink/renderer/core/frame/local_frame.h"',
            ],
        )

        self.patch(
            "third_party/blink/renderer/core/frame/navigator_language.cc",
            "const Vector<String>& NavigatorLanguage::languages() {\n  EnsureUpdatedLanguage();\n  return languages_;\n}",
            (
                "const Vector<String>& NavigatorLanguage::languages() {\n"
                "  static const bool stealth_languages = base::CommandLine::ForCurrentProcess()->HasSwitch(\n"
                '      "stealth-navigator-languages");\n'
                "  if (stealth_languages && languages_.empty()) {\n"
                '    languages_.push_back("en-US");\n'
                '    languages_.push_back("en");\n'
                "    return languages_;\n"
                "  }\n"
                "  EnsureUpdatedLanguage();\n"
                "  return languages_;\n"
                "}"
            ),
            "navigator.languages returns ['en-US', 'en'] with --stealth-navigator-languages",
        )

        # ──────────────────────────────────────────────────────────────────────────────
        # Patch 9: Forward stealth-navigator-languages switch to renderer
        # File: content/browser/renderer_host/render_process_host_impl.cc
        # ──────────────────────────────────────────────────────────────────────────────
        print("Patch 9: forward stealth-navigator-languages switch to renderer")

        self.patch(
            "content/browser/renderer_host/render_process_host_impl.cc",
            "void RenderProcessHostImpl::AppendRendererCommandLine(\n"
            "    base::CommandLine* command_line) {\n"
            "  // Forward custom stealth switches to renderer processes.\n"
            "  const base::CommandLine& browser_cmd =\n"
            "      *base::CommandLine::ForCurrentProcess();\n"
            '  for (const char* sw : {"webgl-unmasked-vendor", "webgl-unmasked-renderer",\n'
            '                          "preload-script", "enable-trusted-synthetic-events"}) {\n'
            "    if (browser_cmd.HasSwitch(sw))\n"
            "      command_line->AppendSwitchASCII(sw, browser_cmd.GetSwitchValueASCII(sw));\n"
            "  }",
            "void RenderProcessHostImpl::AppendRendererCommandLine(\n"
            "    base::CommandLine* command_line) {\n"
            "  // Forward custom stealth switches to renderer processes.\n"
            "  const base::CommandLine& browser_cmd =\n"
            "      *base::CommandLine::ForCurrentProcess();\n"
            '  for (const char* sw : {"webgl-unmasked-vendor", "webgl-unmasked-renderer",\n'
            '                          "preload-script", "enable-trusted-synthetic-events",\n'
            '                          "stealth-navigator-languages", "stealth-viewport-size"}) {\n'
            "    if (browser_cmd.HasSwitch(sw))\n"
            "      command_line->AppendSwitchASCII(sw, browser_cmd.GetSwitchValueASCII(sw));\n"
            "  }",
            "forward stealth-navigator-languages switch to renderer",
        )

        # ──────────────────────────────────────────────────────────────────────────────

    def get_patched_files(self) -> list[str]:
        """Return the deduplicated list of files that are touched by patches."""
        return list(dict.fromkeys(self.patched_files))

    def print_patched_files(self) -> None:
        """Print the list of patched files, one per line."""
        for f in self.get_patched_files():
            print(f)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply Chromium C++ patches")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be patched without writing")
    parser.add_argument("--list-files", action="store_true", help="Print the list of files touched by patches and exit")
    args = parser.parse_args()

    applier = PatchApplier()
    if args.list_files:
        applier.list_files_only = True
        import io

        _old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        applier.run_patches()
        sys.stdout = _old_stdout
        applier.print_patched_files()
        sys.exit(0)

    if args.dry_run:
        applier.dry_run = True
        print("*** DRY RUN — no files will be modified ***\n")

    applier.run_patches()

    if applier.errors:
        print(f"\n{applier.errors} patch(es) failed — see errors above.", file=sys.stderr)
        sys.exit(1)

    if applier.dry_run:
        print("No files modified (dry run).")
    else:
        print("\nAll patches applied successfully.")
