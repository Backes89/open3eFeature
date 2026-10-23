import open3e.Open3Ecodecs
from open3e.Open3Ecodecs import O3EByteVal, O3EComplexType, O3EEnum, O3EInt16, O3EList, O3ESwitch, RawCodec
from open3e.Open3Eclass import O3Eclass

import pytest


def setpoint(name):
    # structure of the ZigBee device setpoints: byte 1 = device type selects the payload
    return O3EComplexType(13, name, [RawCodec(1, "Unknown_00"), O3ESwitch(12, "ViCareDevice", "ViCareDeviceTypes", {
        2: O3EComplexType(11, "Data", [RawCodec(10, "Unknown_02_11"), O3EEnum(1, "DeviceDisplayTurned", "DeviceDisplayModeStates")]),
        3: O3EComplexType(11, "Data", [O3EInt16(2, "MaximumFlowTemperature", scale=10), RawCodec(9, "Unknown_04_12")]),
    }, default=RawCodec(11, "Unknown_02_12"))], acc="rw")


DIDS = {
    2085: setpoint("DistributorSetpoint"),
    2088: setpoint("TrvSetpoint"),
    2091: setpoint("ClimateSensorSetpoint"),
    900: O3EComplexType(8, "Nested", [RawCodec(1, "A"), O3EComplexType(5, "Inner", [O3EInt16(2, "X", scale=10), O3EInt16(2, "Y", scale=10), O3EByteVal(1, "Z")]), RawCodec(2, "B")]),
    901: O3EComplexType(6, "WithList", [RawCodec(1, "A"), O3EList(5, "L", [O3EByteVal(1, "Count"), O3EComplexType(2, "E", [O3EByteVal(1, "a"), O3EByteVal(1, "b")])])]),
    902: O3ESwitch(12, "TopLevelSwitch", "ViCareDeviceTypes", {
        3: O3EComplexType(11, "Data", [O3EInt16(2, "MaximumFlowTemperature", scale=10), RawCodec(9, "Unknown_04_12")]),
    }, default=RawCodec(11, "Unknown_02_12")),
    903: O3EComplexType(9, "MixerOneCircuitRoomTemperatureSetpoint", [O3EInt16(2, "Comfort", signed=True), O3EInt16(2, "Standard", signed=True),
                                                                      O3EInt16(2, "Reduced", signed=True), RawCodec(2, "Unknown2"), O3EByteVal(1, "Unknown1")]),
}

DATA = {
    2085: "00032602000000000000000000",  # floor thermostat, MaximumFlowTemperature 55.0
    2088: "00020000000000000000000001",  # TRV, display turned
    2091: "00010000000000000000000000",  # climate sensor, default case
    900: "aa07e10500bb1234",
    901: "010203040500",
    902: "032602000000000000000000",
    903: "c800c900be00000000",
}


class FakeEcu:
    """O3Eclass without CAN or DoIP connection, reads from DATA and records writes."""
    def __init__(self, data=None):
        self.ecu = O3Eclass.__new__(O3Eclass)
        self.ecu.tx = 0x6c3
        self.ecu.dataIdentifiers = DIDS
        self.data = {did: bytes.fromhex(hx) for did, hx in (data or DATA).items()}
        self.reads = []
        self.written = []
        self.ecu.readPure = self.read_pure
        self.ecu._writeByDid = self.write

    def read_pure(self, did, binary=False):
        self.reads.append(did)
        return self.data[did], f"DID_{did}"

    def write(self, did, val, raw, useService77=False):
        if(open3e.Open3Ecodecs.flag_binary):
            self.written.append((did, bytes(val)))
        else:
            open3e.Open3Ecodecs.flag_rawmode = raw
            self.written.append((did, bytes(DIDS[did].encode(val))))
        return True, 0


@pytest.fixture(autouse=True)
def restore_flags():
    # module wide flags, other test files rely on their own setting
    binary, rawmode = open3e.Open3Ecodecs.flag_binary, open3e.Open3Ecodecs.flag_rawmode
    yield
    open3e.Open3Ecodecs.flag_binary, open3e.Open3Ecodecs.flag_rawmode = binary, rawmode


# --- first level, unchanged behaviour ---

@pytest.mark.parametrize("sub", ["Standard", "standard", "1", 1])
def test_first_level_read_unchanged(sub):
    assert FakeEcu().ecu.readByDid(903, raw=False, sub=sub) == (20.1, "Standard", 903)


def test_first_level_write_unchanged():
    fake = FakeEcu()
    assert fake.ecu.writeByDid(903, "21.5", raw=False, sub="Standard") == (True, 0)
    assert fake.written == [(903, bytes.fromhex("c800d700be00000000"))]
    assert open3e.Open3Ecodecs.flag_binary is False


def test_first_level_error_messages_unchanged():
    ecu = FakeEcu().ecu
    assert ecu.readByDid(903, raw=False, sub="Nope")[0] == "No Sub found according to Nope with DID 903"
    assert ecu.readByDid(903, raw=False, sub=7)[0] == "Sub-Item with Index 7 does not exist with DID 903"
    assert ecu.writeByDid(903, "1", raw=False, sub=7)[0] == "Sub Index 7 does not exist in DID 903"


# --- nested paths ---

def test_nested_read_below_switch():
    ecu = FakeEcu().ecu
    assert ecu.readByDid(2085, raw=False, sub="ViCareDevice.MaximumFlowTemperature") == (55.0, "ViCareDevice/MaximumFlowTemperature", 2085)
    assert ecu.readByDid(2085, raw=False, sub="vicaredevice.maximumflowtemperature")[0] == 55.0
    assert ecu.readByDid(2085, raw=True, sub="ViCareDevice.MaximumFlowTemperature")[0] == "2602"
    assert ecu.readByDid(2091, raw=False, sub="ViCareDevice.Unknown_02_12")[0] == "0000000000000000000000"


def test_nested_read_pseudo_keys():
    ecu = FakeEcu().ecu
    assert ecu.readByDid(2085, raw=False, sub="ViCareDevice.ID") == (3, "ViCareDevice/ID", 2085)
    assert ecu.readByDid(2085, raw=False, sub="ViCareDevice.Text")[0] == "Floor thermostat"
    assert ecu.readByDid(2088, raw=False, sub="ViCareDevice.DeviceDisplayTurned.Text") == ("Turned", "ViCareDevice/DeviceDisplayTurned/Text", 2088)
    assert "not available in raw mode" in ecu.readByDid(2085, raw=True, sub="ViCareDevice.ID")[0]


def test_pseudo_keys_any_case_give_canonical_topic():
    ecu = FakeEcu().ecu
    assert ecu.readByDid(2085, raw=False, sub="vicaredevice.text") == ("Floor thermostat", "ViCareDevice/Text", 2085)
    assert ecu.readByDid(2088, raw=False, sub="ViCareDevice.devicedisplayturned.id") == (1, "ViCareDevice/DeviceDisplayTurned/ID", 2088)


def test_nested_write_replaces_only_the_field():
    fake = FakeEcu()
    assert fake.ecu.writeByDid(2085, "45", raw=False, sub="ViCareDevice.MaximumFlowTemperature") == (True, 0)
    assert fake.ecu.writeByDid(2088, "Standard", raw=False, sub="ViCareDevice.DeviceDisplayTurned") == (True, 0)
    assert fake.ecu.writeByDid(2085, "c201", raw=True, sub="ViCareDevice.MaximumFlowTemperature") == (True, 0)
    assert fake.written == [
        (2085, bytes.fromhex("0003c201000000000000000000")),
        (2088, bytes.fromhex("00020000000000000000000000")),
        (2085, bytes.fromhex("0003c201000000000000000000")),
    ]
    assert open3e.Open3Ecodecs.flag_binary is False


def test_nested_without_switch():
    fake = FakeEcu()
    assert fake.ecu.readByDid(900, raw=False, sub="Inner.Y") == (0.5, "Inner/Y", 900)
    assert fake.ecu.writeByDid(900, "12.3", raw=False, sub="Inner.Y") == (True, 0)
    assert fake.written == [(900, bytes.fromhex("aa07e17b00bb1234"))]


def test_nested_write_reads_from_readecu():
    # listener mode: the current value is read via the other connection
    fake, other = FakeEcu(), FakeEcu()
    def no_read(did, binary=False):
        raise AssertionError("must read via readecu")
    fake.ecu.readPure = no_read
    assert fake.ecu.writeByDid(2085, "45", raw=False, sub="ViCareDevice.MaximumFlowTemperature", readecu=other.ecu) == (True, 0)
    assert fake.ecu.writeByDid(2085, "0003c201000000000000000000", raw=True, readecu=other.ecu) == (True, 0)
    assert other.reads == [2085, 2085]
    assert fake.written == [(2085, bytes.fromhex("0003c201000000000000000000"))] * 2


def test_field_of_other_device_type_is_rejected():
    fake = FakeEcu()
    msg, _ = fake.ecu.writeByDid(2088, "45", raw=False, sub="ViCareDevice.MaximumFlowTemperature")
    assert "MaximumFlowTemperature in ViCareDevice with ID 2" in msg
    assert "with ID 2" in fake.ecu.readByDid(2088, raw=False, sub="ViCareDevice.MaximumFlowTemperature")[0]
    assert fake.written == []


@pytest.mark.parametrize("did, sub", [(2085, "ViCareDevice.0"), (2085, "1.0"), (900, "Inner.1")])
def test_no_index_below_first_level(did, sub):
    fake = FakeEcu()
    assert "is not supported in" in fake.ecu.readByDid(did, raw=False, sub=sub)[0]
    assert "is not supported in" in fake.ecu.writeByDid(did, "1", raw=False, sub=sub)[0]
    assert fake.written == []


def test_path_into_list_is_rejected():
    fake = FakeEcu()
    assert "Sub path into O3EList L is not supported" in fake.ecu.readByDid(901, raw=False, sub="L.Count")[0]
    assert "Sub path into O3EList L is not supported" in fake.ecu.writeByDid(901, "1", raw=False, sub="L.Count")[0]
    assert fake.written == []


@pytest.mark.parametrize("sub", ["ViCareDevice.", "ViCareDevice..MaximumFlowTemperature"])
def test_empty_path_element_is_rejected(sub):
    assert "Empty element in sub path" in FakeEcu().ecu.readByDid(2085, raw=False, sub=sub)[0]


@pytest.mark.parametrize("sub", ["ViCareDevice.ID", "ViCareDevice.Text", "ViCareDevice.MaximumFlowTemperature.X"])
def test_pseudo_keys_can_not_be_written(sub):
    fake = FakeEcu()
    assert "can not be written by sub path" in fake.ecu.writeByDid(2085, "2", raw=False, sub=sub)[0]
    assert fake.written == []


def test_incomplete_or_failed_read():
    fake = FakeEcu({**DATA, 2085: "0003"})
    assert "received 2 bytes, expected 13" in fake.ecu.readByDid(2085, raw=False, sub="ViCareDevice.MaximumFlowTemperature")[0]
    fake.ecu.readPure = lambda did, binary=False: ("negative response, 49:requestOutOfRange", f"DID_{did}")
    assert "Reading DID 2085 failed" in fake.ecu.writeByDid(2085, "45", raw=False, sub="ViCareDevice.MaximumFlowTemperature")[0]
    assert fake.written == []


# --- the ID of an O3ESwitch (device type) can not be changed by writing ---

def test_writing_whole_switch_with_other_id_is_rejected():
    fake = FakeEcu()
    other = {"ID": 2, "Unknown_02_11": "00000000000000000000", "DeviceDisplayTurned": "Turned"}
    msg, _ = fake.ecu.writeByDid(2085, other, raw=False, sub="ViCareDevice")
    assert "ID 2 differs from ID 3" in msg
    msg, _ = fake.ecu.writeByDid(2085, "02" + "00" * 11, raw=True, sub="ViCareDevice")
    assert "ID 2 differs from ID 3" in msg
    assert fake.written == []
    assert open3e.Open3Ecodecs.flag_binary is False


def test_writing_whole_switch_with_same_id():
    fake = FakeEcu()
    same = {"ID": 3, "MaximumFlowTemperature": 45, "Unknown_04_12": "000000000000000000"}
    assert fake.ecu.writeByDid(2085, same, raw=False, sub="ViCareDevice") == (True, 0)
    assert fake.written == [(2085, bytes.fromhex("0003c201000000000000000000"))]


def test_writing_whole_did_checks_switch_ids():
    fake = FakeEcu()
    other = {"Unknown_00": "00", "ViCareDevice": {"ID": 2, "Unknown_02_11": "00000000000000000000", "DeviceDisplayTurned": "Turned"}}
    assert "ID 2 differs from ID 3" in fake.ecu.writeByDid(2085, other, raw=False)[0]
    assert "ID 2 differs from ID 3" in fake.ecu.writeByDid(2085, "0002" + "00" * 11, raw=True)[0]
    assert fake.written == []
    assert fake.ecu.writeByDid(2085, "0003c201000000000000000000", raw=True) == (True, 0)
    assert fake.written == [(2085, bytes.fromhex("0003c201000000000000000000"))]


def test_writing_whole_did_without_switch_does_not_read():
    fake = FakeEcu()
    assert fake.ecu.writeByDid(903, "c800d700be00000000", raw=True) == (True, 0)
    assert fake.reads == []


# --- O3ESwitch as top-level codec of a DID: names only, also on the first level ---

def test_top_level_switch():
    fake = FakeEcu()
    assert fake.ecu.readByDid(902, raw=False, sub="MaximumFlowTemperature") == (55.0, "MaximumFlowTemperature", 902)
    assert fake.ecu.readByDid(902, raw=False, sub="ID") == (3, "ID", 902)
    assert "is not supported in" in fake.ecu.readByDid(902, raw=False, sub="0")[0]
    assert fake.ecu.writeByDid(902, "45", raw=False, sub="MaximumFlowTemperature") == (True, 0)
    assert fake.written == [(902, bytes.fromhex("03c201000000000000000000"))]


def test_switch_without_default_and_unknown_id():
    dids = {**DIDS, 904: O3EComplexType(3, "NoDefault", [O3ESwitch(3, "Dev", "ViCareDeviceTypes", {
        3: O3EComplexType(2, "Data", [O3EInt16(2, "MaximumFlowTemperature", scale=10)]),
    })])}
    fake = FakeEcu({**DATA, 904: "052602"})
    fake.ecu.dataIdentifiers = dids
    assert fake.ecu.readByDid(904, raw=False, sub="Dev.MaximumFlowTemperature")[0] == "Dev: no matching case for ID 5 with DID 904"
    assert fake.ecu.writeByDid(904, "45", raw=False, sub="Dev.MaximumFlowTemperature")[0] == "Dev: no matching case for ID 5 with DID 904"
    assert fake.written == []
