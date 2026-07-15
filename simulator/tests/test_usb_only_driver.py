import USB_Only_Driver as usb_driver


class _FakeEndpoint:
    def __init__(self, address):
        self.bEndpointAddress = address


class _FakeInterface:
    def __init__(self, interface_class, endpoints):
        self.bInterfaceClass = interface_class
        self._endpoints = endpoints

    def __iter__(self):
        return iter(self._endpoints)


class _FakeConfig:
    def __init__(self, interfaces):
        self._interfaces = interfaces

    def __iter__(self):
        return iter(self._interfaces)


class _FakeDeviceWithConfig:
    def __init__(self, cfg):
        self._cfg = cfg

    def get_active_configuration(self):
        return self._cfg


def test_finds_bulk_out_endpoint_on_a_standard_usb_printer_class_interface():
    out_ep = _FakeEndpoint(0x01)
    in_ep = _FakeEndpoint(0x82)
    printer_class_interface = _FakeInterface(0x07, [out_ep, in_ep])
    dev = _FakeDeviceWithConfig(_FakeConfig([printer_class_interface]))

    found = usb_driver.find_bulk_out_endpoint(dev)

    assert found is out_ep


def test_finds_bulk_out_endpoint_on_a_vendor_class_interface():
    out_ep = _FakeEndpoint(0x01)
    vendor_class_interface = _FakeInterface(0xFF, [out_ep])
    dev = _FakeDeviceWithConfig(_FakeConfig([vendor_class_interface]))

    found = usb_driver.find_bulk_out_endpoint(dev)

    assert found is out_ep


class _FakeDeviceThatWontOpen:
    def is_kernel_driver_active(self, interface):
        raise NotImplementedError

    def set_configuration(self):
        raise NotImplementedError("Operation not supported or unimplemented on this platform")


def test_print_raw_usb_reports_clean_error_when_device_cannot_be_opened(monkeypatch, capsys):
    monkeypatch.setattr(usb_driver.usb.core, "find", lambda **kwargs: _FakeDeviceThatWontOpen())

    usb_driver.print_raw_usb(b"data")

    out = capsys.readouterr().out
    assert "[ERROR]" in out
