---
name: improve-wezterm-config
description: Improve current wezterm configuration implemented in Lua
disallowed-tools: pwsh, powershell, posix utilities
effort: max
---

Current implementation is available at:
c:\repos\config\wezterm\

Consider this implementation canonical, best version, ignore the git history and the stale AGENTS.md remarks, and look only for improvements on top of what's there.

Review current Lua code in context of following two criteria:
1. Stability of function for currently implemented features. Some regularly reoccuring issues are tab and status cacheing and UI strings update including corrent and fluent running timer update, which in some rare occasions result in incorrect state and display. Make possible hardening and stabilization without bloating the code or sacrificing the performance, entire function must stay very snappy, request which might result in fragile implementation patterns.
2. Performance is highly regarded, so identify improvement opportunities while keeping functionality and stability at high level. Consider only perfomence improvements which could result in multiple milliseconds reduction not less than that.

Don't use powershell or posix utils, only standard windows shell utils.
