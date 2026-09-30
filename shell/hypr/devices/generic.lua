-- Generic phone: preferred mode, automatic scale. Copy this file to add a device.
return {
  monitors = {
    { output = "", mode = "preferred", position = "0x0", scale = "auto" },
  },
  touchdevice = {},          -- { output = "DSI-1", transform = 0 }
  keys = {},                 -- defaults: XF86HomePage, XF86PowerOff, XF86Audio*
  kb_layout = "us",
  terminal = "foot",
}
