"""Keep operation menus positioned after their popup is mounted."""

from nicegui.elements.select import Select


class OperationSelect(Select):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # QSelect emits popup-show before QMenu mounts its portal. After a
        # card/layout update the initial positioning can miss that portal,
        # leaving q-position-engine at visibility:collapse. Position the menu
        # after Vue's update and browser layout, entirely on the client.
        self.on(
            "popup-show",
            js_handler=f"""() => {{
                const control = getElement({self.id}).$refs.qRef;
                control.$nextTick(() => requestAnimationFrame(() => {{
                    if (control.$el?.isConnected) control.updateMenuPosition();
                }}));
            }}""",
        )
