"""
UsageGraphics.py - Placeholder Module for ErgoProtect
------------------------------------------------
This module is not yet implemented.
It will be replaced in a future iteration of ErgoProtect.

This placeholder exists so that GraphicalInterface.py can detect the
module and show a friendly "not implemented" message instead of crashing.
"""

import tkinter as tk


def create_tab(parent, config_manager) -> tk.Label:
    """
    Creates a placeholder tab indicating this module is not yet present.

    Args:
        parent:         The parent notebook frame provided by GraphicalInterface.
        config_manager: Shared ConfigManager (unused here, kept for API consistency).

    Returns:
        The Label widget.
    """
    label = tk.Label(
        parent,
        text="Module not present.",
        font=("Segoe UI", 13),
        foreground="#aaaaaa",
    )
    label.pack(expand=True)
    return label
