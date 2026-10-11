

def test_raw_format_emits_the_vendor_line_verbatim():
    """RAW must put the vendor's own line on the wire, NOT key=value pairs --
    the modeling rules regex the line itself."""
    from app.override_sender import OverrideSender
    s = OverrideSender.__new__(OverrideSender)
    s.data_type = "RAW"; s.vendor = "microsoft"; s.product = "windows"
    line = ("9/2/2026 2:21:39 PM 0AE4 PACKET 000001F0A4F0AC50 UDP Rcv "
            "ANSWER SECTION: TYPE A DATA 93.184.216.34 AUTHORITY SECTION:")
    out = s.format_record({"_raw_log": line, "questionName": "www.example.com"})
    assert line in out
    assert out.startswith("<")                 # syslog framed
    assert "questionName=" not in out          # NOT flattened to key=value


def test_raw_format_falls_back_when_no_raw_log_present():
    from app.override_sender import OverrideSender
    s = OverrideSender.__new__(OverrideSender)
    s.data_type = "RAW"; s.vendor = "v"; s.product = "p"
    out = s.format_record({"foo": "bar"})
    assert "foo=bar" in out                    # diagnosable, not an empty frame
