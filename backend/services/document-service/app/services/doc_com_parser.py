"""DOC parser using Windows COM automation via pywin32.

Strategy: open .doc with Word.Application via DispatchEx, extract Content.Text,
split on \r to get paragraphs.

DispatchEx creates a new Word instance (avoiding stale cached singletons).
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import List

log = logging.getLogger("document-service.doc_com")

COM_AVAILABLE: bool = False

try:
    import win32com.client
    import pythoncom
    COM_AVAILABLE = True
except ImportError:
    pass


def extract_text_com(data: bytes, filename: str) -> List[str]:
    """Extract paragraphs from legacy .doc using Word COM automation.

    Returns list of paragraph strings (one per \r-separated segment).
    """
    if not COM_AVAILABLE or os.name != "nt":
        return []

    tmp_path: str = ""
    word = None
    doc = None
    try:
        # Write bytes to real temp file (Word requires filesystem path)
        fd, tmp_path = tempfile.mkstemp(suffix=".doc")
        os.write(fd, data)
        os.close(fd)

        pythoncom.CoInitialize()

        try:
            # DispatchEx creates a fresh Word instance (avoids stale cache issues)
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0  # wdAlertsNone

            try:
                # Normalize to Windows path separators
                abs_path = os.path.abspath(tmp_path).replace("/", "\\")
                doc = word.Documents.Open(
                    FileName=abs_path,
                    ConfirmConversions=False,
                    ReadOnly=True,
                    AddToRecentFiles=False,
                )

                content: str = doc.Content.Text
                if not content:
                    return []

                lines: List[str] = []
                for seg in content.split("\r"):
                    seg = seg.strip()
                    if seg:
                        lines.append(seg)
                return lines
            finally:
                if doc is not None:
                    try:
                        doc.Close(False)
                    except Exception:
                        pass
                    doc = None
        finally:
            if word is not None:
                try:
                    word.Quit()
                except Exception:
                    pass
                word = None
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    except Exception as exc:
        log.warning("Word COM failed for %s: %s", filename, exc)
        return []
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass
