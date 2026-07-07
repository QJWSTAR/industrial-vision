"""Controller layer — bridges UI and Service layers.

Controllers manage application state, coordinate workflows, and expose
a clean API for UI components. UI components never directly access
Services or Engines.

Note: AppController and WorkflowController were removed as dead code.
The main application (MainWindow) currently coordinates workflows directly.
"""
