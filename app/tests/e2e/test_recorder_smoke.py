from talkboard.db import Status


def wait_for_chunks(page, count):
    page.wait_for_function(
        "n => Number(document.querySelector('#chunks-uploaded').textContent) >= n",
        arg=count,
        timeout=15000,
    )


def test_recording_from_the_microphone_saves_audio_and_stops(live_server, launch_browser):
    page = launch_browser()
    page.goto(f"{live_server.url}/?timeslice=500")

    page.fill("#title", "Smoke talk")
    page.check("input[name=source][value=mic]")
    page.select_option("#language", "yue")
    page.fill("#word-list", "OpenAI, Anthropic")
    page.click("#start")

    page.wait_for_selector("#status:has-text('Recording')")
    wait_for_chunks(page, 3)
    page.click("#stop")
    page.wait_for_selector("#status:has-text('Saved')", timeout=15000)

    (talk,) = live_server.app.state.db.list_talks()
    assert talk.title == "Smoke talk"
    assert talk.source == "mic"
    assert talk.language == "yue"
    assert talk.word_list == "OpenAI, Anthropic"
    assert talk.status is Status.RECORDED
    with open(talk.audio_path, "rb") as audio:
        assert len(audio.read()) > 1000


def test_a_silent_microphone_triggers_a_warning(live_server, launch_browser, silent_wav):
    page = launch_browser(
        [f"--use-file-for-fake-audio-capture={silent_wav}"]
    )
    page.goto(f"{live_server.url}/?timeslice=500&silence_check_ms=1500")

    page.fill("#title", "Silent talk")
    page.click("#start")

    page.wait_for_selector("#warning:not([hidden])", timeout=10000)
    assert "silent" in page.inner_text("#warning").lower()


def test_start_is_blocked_when_the_stream_has_no_audio_track(live_server, launch_browser):
    page = launch_browser()
    page.add_init_script(
        """
        navigator.mediaDevices.getDisplayMedia = async () => {
          const canvas = document.createElement('canvas');
          return canvas.captureStream();  // video only, as when 'Share tab audio' is unticked
        };
        """
    )
    page.goto(f"{live_server.url}/")
    page.check("input[name=source][value=tab]")
    page.click("#start")

    page.wait_for_selector("#error:not([hidden])")
    assert "audio" in page.inner_text("#error").lower()
    assert live_server.app.state.db.list_talks() == []


def test_a_normal_microphone_shows_no_silence_warning(live_server, launch_browser, tone_wav):
    page = launch_browser([f"--use-file-for-fake-audio-capture={tone_wav}"])
    page.goto(f"{live_server.url}/?timeslice=500&silence_check_ms=1500")

    page.fill("#title", "Loud talk")
    page.click("#start")
    page.wait_for_selector("#status:has-text('Recording')")
    page.wait_for_timeout(2500)  # past the silence check

    assert page.is_hidden("#warning")
    page.click("#stop")
