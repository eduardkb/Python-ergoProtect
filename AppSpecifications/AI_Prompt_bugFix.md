Modify Python application code attached as a project.
use as few AI resources as possible.
don't write text explaining the code. while it is being written.
priority is to generate the code as per requirements below.

====================
Requirements:
 - when exiting through the tray icon exit option I get exeption below although the app exits. ( the exit button on the general tab works and does not display this error)
            PS C:\Users\eduard\dev\Python-ergoProtect\src> python .\main.py
            Exception in Tkinter callback
            Traceback (most recent call last):
            File "C:\Python314\Lib\tkinter\__init__.py", line 2093, in __call__
                return self.func(*args)
                    ~~~~~~~~~^^^^^^^
            File "C:\Python314\Lib\tkinter\__init__.py", line 876, in callit
                func(*args, **kw)
                ~~~~^^^^^^^^^^^^^
            File "C:\Users\eduard\dev\Python-ergoProtect\src\main.py", line 217, in <lambda>
                gui.root.after(0, lambda: _shutdown(icon, gui))
                                        ~~~~~~~~~^^^^^^^^^^^
            File "C:\Users\eduard\dev\Python-ergoProtect\src\main.py", line 249, in _shutdown
                keyboard_service.stop()
                ~~~~~~~~~~~~~~~~~~~~~^^
            File "C:\Users\eduard\dev\Python-ergoProtect\src\KeyboardActions.py", line 554, in stop
                self._stop_drag_mouse_listener()
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
======================
On every modification also:
- Inside file "GraphicalInterface.py" update the variable "APP_VERSION" so that the Major and minor number stay the same but the patch number is increased by 1. (1.0.7 to 1.0.8)
- also on create file "\src\changelog.md" if not existant. and on the top of the file (to maintain new changes on top) write the new version number and add a description on what was changed (do a summary only and don't be too technical).