"""Phase 3 -- volume, mute, play/pause/next/previous.

Volume/mute via `osascript -e "set volume ..."`; play/pause/next/previous via
system-defined media key events through pyobjc, so it drives whatever's
actually playing rather than one hardcoded app. See PLAN.md section 3 for the
handler contract and section 4 for reference repos (thevickypedia/Jarvis has
working volume/brightness key handling worth reading first).

Not implemented yet.
"""
from __future__ import annotations
