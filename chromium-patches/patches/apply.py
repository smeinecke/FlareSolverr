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

    def patch(self, rel_path: str, old: str, new: str, description: str, fallbacks: "list[str] | None" = None, required: bool = True) -> None:
        if rel_path not in self.patched_files:
            self.patched_files.append(rel_path)
        if self.list_files_only:
            return

        p = pathlib.Path(rel_path)
        if not p.exists():
            if not required:
                print(f"  SKIP  {rel_path}  ({description} – file not found, optional)")
                return
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

        if not required:
            print(f"  SKIP  {rel_path}  ({description} – old string not found, optional)")
            return
        print(f"\nERROR [{description}]: target string not found in {rel_path}", file=sys.stderr)
        print(f"  Searched for: {old[:120]!r}", file=sys.stderr)
        print("  Nearest context in file:", file=sys.stderr)
        for line in self._ctx(content, old).splitlines():
            print(f"    {line}", file=sys.stderr)
        self.errors += 1

    def patch_regex(
        self,
        rel_path: str,
        pattern: str,
        replacement: str,
        description: str,
        flags: int = 0,
    ) -> None:
        """Apply a regex-based patch.

        Searches `rel_path` for `pattern` and replaces the first match with
        `replacement`.  If `replacement` is already present, skips.
        """
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
        if replacement in content:
            print(f"  SKIP  {rel_path}  ({description} – already patched)")
            return

        m = re.search(pattern, content, flags)
        if m:
            if self.dry_run:
                print(f"  WOULD_PATCH  {rel_path}  ({description})")
            else:
                p.write_text(content[: m.start()] + replacement + content[m.end() :])
                print(f"  OK  {rel_path}  ({description})")
            return

        print(f"\nERROR [{description}]: regex not found in {rel_path}", file=sys.stderr)
        print(f"  Pattern: {pattern[:120]!r}", file=sys.stderr)
        print("  Nearest context in file:", file=sys.stderr)
        for line in self._ctx(content, pattern).splitlines():
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
        # NOTE: Patch 1 (global --enable-trusted-synthetic-events) has been removed.
        # Forcing isTrusted=true for all script-dispatched events is detectable and
        # unnecessary: ChromeDriver CDP input events are already trusted by the
        # browser. Arbitrary synthetic events must report isTrusted=false.

        # ──────────────────────────────────────────────────────────────────────────────
        # Patch 2: navigator.webdriver → undefined via [RuntimeEnabled=AutomationControlled]
        #
        # Strategy: gate the IDL attribute on the AutomationControlled Blink runtime
        # feature. When Chrome is launched with
        #   --disable-blink-features=AutomationControlled
        # the feature is OFF → the property does not exist on Navigator → JS reads it
        # as `undefined` (not `false`, not `null`).
        #
        # This avoids:
        #   • typeof null === "object"  (the old boolean? / std::nullopt approach)
        #   • detectable prototype getter overrides (JS-only workaround)
        #
        # No C++ implementation changes needed - just the IDL attribute annotation.
        # Chrome 112+: moved to core/frame/navigator_automation_information.idl.
        # ──────────────────────────────────────────────────────────────────────────────
        print("Patch 2: navigator.webdriver → undefined via [RuntimeEnabled=AutomationControlled]")

        # Chrome 112+: navigator_automation_information.idl in core/frame/
        # The attribute already has [RuntimeEnabled=AutomationControlled] checked at
        # runtime via RuntimeEnabledFeatures. We add it at the IDL level so the Blink
        # bindings generator makes the property absent (not just false) when the
        # feature is disabled.
        self.patch(
            "third_party/blink/renderer/core/frame/navigator_automation_information.idl",
            "    readonly attribute boolean webdriver;",
            "    [RuntimeEnabled=AutomationControlled] readonly attribute boolean webdriver;",
            "gate webdriver on AutomationControlled runtime feature",
            fallbacks=[
                # Old Patch 2 left the IDL as boolean? - normalise it first.
                "    readonly attribute boolean? webdriver;",
                # Older Chrome: modules/navigatorcontrolled/
                "readonly attribute boolean webdriver;",
            ],
        )

        # Revert any C++ changes left behind by the previous Patch 2 approach
        # (std::nullopt / std::optional<bool>). These are no-ops on a fresh tree.
        self.patch(
            "third_party/blink/renderer/core/frame/navigator.h",
            "  std::optional<bool> webdriver() const;",
            "  bool webdriver() const;",
            "revert old Patch 2 header change (std::optional → bool)",
            required=False,
        )
        self.patch(
            "third_party/blink/renderer/core/frame/navigator.cc",
            "std::optional<bool> Navigator::webdriver() const {\n  return std::nullopt;\n}",
            "bool Navigator::webdriver() const {\n"
            "  if (RuntimeEnabledFeatures::AutomationControlledEnabled())\n"
            "    return true;\n"
            "\n"
            "  bool automation_enabled = false;\n"
            "  probe::ApplyAutomationOverride(GetExecutionContext(), automation_enabled);\n"
            "  return automation_enabled;\n"
            "}",
            "revert old Patch 2 C++ implementation (std::nullopt → original)",
            required=False,
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
        # to renderer processes - they must be explicitly copied in AppendRendererCommandLine
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
            '                          "preload-script"}) {\n'
            "    if (browser_cmd.HasSwitch(sw))\n"
            "      command_line->AppendSwitchASCII(sw, browser_cmd.GetSwitchValueASCII(sw));\n"
            "  }",
            "forward stealth switches from browser to renderer process command line",
        )

        # ──────────────────────────────────────────────────────────────────────────────
        # Patch 4: --preload-script flag (document_start injection via raw V8)
        # Hook into RenderFrameImpl::DidCreateDocumentElement - fires AFTER V8 context
        # creation is complete, so it is safe to compile and run scripts.
        # DO NOT use DidCreateScriptContext: that fires DURING V8 context creation while
        # V8 holds internal spinlocks; calling Script::Compile there spins at 97% CPU.
        # Uses raw V8 with kDoNotRunMicrotasks to prevent microtask-queue re-entrancy spin.
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
            '#include "v8/include/v8.h"',
            after_patterns=[
                '#include "base/files/file_util.h"',
                '#include "base/command_line.h"',
            ],
        )

        _PRELOAD_INJECTION = (
            "  // --preload-script: evaluate JS file before any page scripts.\n"
            "  // Uses raw V8 with kDoNotRunMicrotasks to prevent microtask re-entrancy spin.\n"
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
            "      v8::Isolate* isolate = v8::Isolate::GetCurrent();\n"
            "      v8::Local<v8::Context> ctx =\n"
            "          GetWebFrame()->MainWorldScriptContext();\n"
            "      if (isolate && !ctx.IsEmpty()) {\n"
            "        v8::HandleScope handle_scope(isolate);\n"
            "        v8::Context::Scope context_scope(ctx);\n"
            "        v8::MicrotasksScope no_microtasks(\n"
            "            isolate, ctx->GetMicrotaskQueue(),\n"
            "            v8::MicrotasksScope::kDoNotRunMicrotasks);\n"
            "        v8::TryCatch try_catch(isolate);\n"
            "        v8::Local<v8::String> src;\n"
            "        if (v8::String::NewFromUtf8(\n"
            "                isolate, preload_script_content->c_str()).ToLocal(&src)) {\n"
            "          v8::Local<v8::Script> script;\n"
            "          if (v8::Script::Compile(ctx, src).ToLocal(&script)) {\n"
            "            v8::Local<v8::Value> result;\n"
            "            (void)script->Run(ctx).ToLocal(&result);\n"
            "          }\n"
            "        }\n"
            "      }\n"
            "    }\n"
            "  }\n"
        )

        # Main-frame preload injection is disabled: running v8::Script from
        # DidCreateDocumentElement causes 100% CPU spin (same as DidCreateScriptContext).
        # kDoNotRunMicrotasks does not fix it. Main frame uses CDP
        # Page.addScriptToEvaluateOnNewDocument instead - see utils.py.
        # _PRELOAD_INJECTION is kept above for future investigation.

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
            '#include "v8/include/v8.h"',
            after_patterns=[
                '#include "base/files/file_util.h"',
            ],
        )

        _WORKER_PRELOAD = (
            "  // --preload-script: evaluate preload content before any user worker scripts.\n"
            "  // Uses raw V8 with kDoNotRunMicrotasks to prevent microtask-queue draining\n"
            "  // from re-entering the worker lifecycle and causing a CPU spin.\n"
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
            "      v8::Isolate* isolate = ScriptController()->GetScriptState()->GetIsolate();\n"
            "      v8::HandleScope handle_scope(isolate);\n"
            "      v8::Local<v8::Context> ctx = ScriptController()->GetScriptState()->GetContext();\n"
            "      v8::MicrotasksScope no_microtasks(\n"
            "          isolate, ctx->GetMicrotaskQueue(),\n"
            "          v8::MicrotasksScope::kDoNotRunMicrotasks);\n"
            "      v8::TryCatch try_catch(isolate);\n"
            "      v8::Local<v8::String> src;\n"
            "      if (v8::String::NewFromUtf8(isolate, preload_content->c_str()).ToLocal(&src)) {\n"
            "        v8::Local<v8::Script> script;\n"
            "        if (v8::Script::Compile(ctx, src).ToLocal(&script)) {\n"
            "          v8::Local<v8::Value> result;\n"
            "          (void)script->Run(ctx).ToLocal(&result);\n"
            "        }\n"
            "      }\n"
            "    }\n"
            "  }\n"
        )

        # Worker prelude injection is disabled: running v8::Script from
        # DidFetchClassicScript causes 100% CPU spin regardless of MicrotasksScope
        # suppression. C++ Patches 2/3/8 already cover all signals that
        # hasInconsistentWorkerValues checks (webdriver, languages, WebGL).
        # _WORKER_PRELOAD is kept above for future investigation.

        # ──────────────────────────────────────────────────────────────────────────────
        # Patch 6: Remove "HeadlessChrome" product name token from UA string and
        # userAgentData brand lists - replace with plain "Chrome" so headless mode
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
                "  // Note: do NOT call window->innerWidth() here - that recurses back into\n"
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
                "  // Note: do NOT call window->innerHeight() here - that recurses back into\n"
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
        # Patch 8: Navigator languages to use the value of --stealth-navigator-languages
        # Headless Chrome returns a single locale or [] which is detectable.
        # The switch value (comma-separated list) becomes the underlying language state
        # consumed by both navigator.language and navigator.languages, so Window,
        # DedicatedWorker and SharedWorker see the same list without realm-specific JS.
        # Falls back to ['en-US', 'en'] when the switch is present with no value.
        # File: third_party/blink/renderer/core/frame/navigator_language.cc
        # ──────────────────────────────────────────────────────────────────────────────
        print("Patch 8: navigator.languages reads --stealth-navigator-languages value")

        self.add_include(
            "third_party/blink/renderer/core/frame/navigator_language.cc",
            '#include "base/command_line.h"',
            after_patterns=[
                '#include "third_party/blink/renderer/core/frame/navigator_language.h"',
                '#include "third_party/blink/renderer/core/frame/local_frame.h"',
            ],
        )

        self.add_include(
            "third_party/blink/renderer/core/frame/navigator_language.cc",
            "#include <string_view>",
            after_patterns=[
                '#include "third_party/blink/renderer/core/frame/navigator_language.h"',
            ],
        )

        self.add_include(
            "third_party/blink/renderer/core/frame/navigator_language.cc",
            '#include "base/containers/span.h"',
            after_patterns=[
                '#include <string_view>',
            ],
        )

        self.add_include(
            "third_party/blink/renderer/core/frame/navigator_language.cc",
            '#include "base/strings/string_split.h"',
            after_patterns=[
                '#include "base/containers/span.h"',
            ],
        )

        self.add_include(
            "third_party/blink/renderer/core/frame/navigator_language.cc",
            '#include "base/strings/string_util.h"',
            after_patterns=[
                '#include "base/strings/string_split.h"',
            ],
        )

        self.patch(
            "third_party/blink/renderer/core/frame/navigator_language.cc",
            "const Vector<String>& NavigatorLanguage::languages() {\n  EnsureUpdatedLanguage();\n  return languages_;\n}",
            (
                "const Vector<String>& NavigatorLanguage::languages() {\n"
                "  static const bool stealth_languages = base::CommandLine::ForCurrentProcess()->HasSwitch(\n"
                '      "stealth-navigator-languages");\n'
                "  if (stealth_languages) {\n"
                "    languages_.clear();\n"
                "    std::string value = base::CommandLine::ForCurrentProcess()\n"
                '                            ->GetSwitchValueASCII("stealth-navigator-languages");\n'
                "    if (!value.empty()) {\n"
                "      for (const auto& token : base::SplitString(\n"
                '               value, ",", base::TRIM_WHITESPACE,\n'
                "               base::SPLIT_WANT_NONEMPTY)) {\n"
                "        languages_.push_back(\n"
                "            String::FromUtf8(base::as_byte_span(\n"
                "                std::string_view(token))));\n"
                "      }\n"
                "    }\n"
                "    if (languages_.empty()) {\n"
                '      languages_.push_back("en-US");\n'
                '      languages_.push_back("en");\n'
                "    }\n"
                "    return languages_;\n"
                "  }\n"
                "  EnsureUpdatedLanguage();\n"
                "  return languages_;\n"
                "}"
            ),
            "navigator.languages uses --stealth-navigator-languages switch value",
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
            '                          "preload-script"}) {\n'
            "    if (browser_cmd.HasSwitch(sw))\n"
            "      command_line->AppendSwitchASCII(sw, browser_cmd.GetSwitchValueASCII(sw));\n"
            "  }",
            "void RenderProcessHostImpl::AppendRendererCommandLine(\n"
            "    base::CommandLine* command_line) {\n"
            "  // Forward custom stealth switches to renderer processes.\n"
            "  const base::CommandLine& browser_cmd =\n"
            "      *base::CommandLine::ForCurrentProcess();\n"
            '  for (const char* sw : {"webgl-unmasked-vendor", "webgl-unmasked-renderer",\n'
            '                          "preload-script", "stealth-navigator-languages",\n'
            '                          "stealth-viewport-size"}) {\n'
            "    if (browser_cmd.HasSwitch(sw))\n"
            "      command_line->AppendSwitchASCII(sw, browser_cmd.GetSwitchValueASCII(sw));\n"
            "  }",
            "forward stealth-navigator-languages switch to renderer",
        )

        # ──────────────────────────────────────────────────────────────────────────────
        # Patch 10: Set ICU default locale from --lang in every renderer process
        # On Linux/Windows the renderer otherwise keeps the OS ICU default, so
        # Intl.* defaults diverge from the patched navigator.language in
        # headless or non-matching host locales.  ChromeOS already had this; we
        # generalize it to all platforms where the browser passes --lang.
        # File: content/renderer/renderer_main.cc
        # ──────────────────────────────────────────────────────────────────────────────
        print("Patch 10: set ICU default locale from --lang for all renderers")

        self.patch(
            "content/renderer/renderer_main.cc",
            (
                "#if BUILDFLAG(IS_CHROMEOS)\n"
                "  // As the Zygote process starts up earlier than the browser process, it gets\n"
                "  // its own locale (at login time for Chrome OS). So we have to set the ICU\n"
                "  // default locale for the renderer process here.\n"
                "  // ICU locale will be used for fallback font selection, etc.\n"
                "  if (command_line.HasSwitch(switches::kLang)) {\n"
                "    const std::string locale =\n"
                "        command_line.GetSwitchValueASCII(switches::kLang);\n"
                "    base::i18n::SetICUDefaultLocale(locale);\n"
                "  }\n"
                "\n"
                "  // When we start the renderer on ChromeOS if the system has core scheduling\n"
                "  // available we want to turn it on.\n"
                "  chromeos::system::EnableCoreSchedulingIfAvailable();\n"
                "#endif  // BUILDFLAG(IS_CHROMEOS)"
            ),
            (
                "  // Set the ICU default locale from --lang in every renderer process.  This\n"
                "  // keeps Intl.* defaults aligned with navigator.language in headless or\n"
                "  // embedded environments where the renderer would otherwise inherit the OS\n"
                "  // locale (e.g. a German host running with --accept-lang=en-US,en).\n"
                "  if (command_line.HasSwitch(switches::kLang)) {\n"
                "    const std::string locale =\n"
                "        command_line.GetSwitchValueASCII(switches::kLang);\n"
                "    base::i18n::SetICUDefaultLocale(locale);\n"
                "  }\n"
                "\n"
                "#if BUILDFLAG(IS_CHROMEOS)\n"
                "  // When we start the renderer on ChromeOS if the system has core scheduling\n"
                "  // available we want to turn it on.\n"
                "  chromeos::system::EnableCoreSchedulingIfAvailable();\n"
                "#endif  // BUILDFLAG(IS_CHROMEOS)"
            ),
            "set ICU default locale from --lang in every renderer process",
        )

        # ──────────────────────────────────────────────────────────────────────────────
        # Patch 11: Remove chromedriver CDC variable injection
        # (Formerly Patch 10; renumbered after adding locale patch.)
        # ChromeDriver injects window.cdc_adoQpoasnfa76pfcZLmcfl_* aliases into
        # every page via Page.addScriptToEvaluateOnNewDocument / Runtime.evaluate.
        # These variables are a well-known automation fingerprint.
        # The injected JS files (execute_script.js, call_function.js, etc.) all
        # fall back to window.Promise / window.Array / ... when the CDC alias is
        # missing (window.cdc_... || window.X), so removing the injection is
        # safe for chromedriver runtime operation.
        # ──────────────────────────────────────────────────────────────────────────────
        print("Patch 10: remove chromedriver CDC (window.cdc_*) injection")

        self.patch_regex(
            "chrome/test/chromedriver/chrome/devtools_client_impl.cc",
            r'std::string script =\s*"\(function \(\) \{"\s*(?:"window\.cdc_[^"]+;"\s*)*"\}\) \(\);"\s*;',
            'std::string script =\n'
            '        "(function () {})();";',
            "remove CDC alias injection from chromedriver SetUpDevTools",
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
        print("*** DRY RUN - no files will be modified ***\n")

    applier.run_patches()

    if applier.errors:
        print(f"\n{applier.errors} patch(es) failed - see errors above.", file=sys.stderr)
        sys.exit(1)

    if applier.dry_run:
        print("No files modified (dry run).")
    else:
        print("\nAll patches applied successfully.")
