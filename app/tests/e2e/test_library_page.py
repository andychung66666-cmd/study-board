import os
import time

from talkboard.db import Status


def seed(live, title, status=Status.DONE, segments=(), error=None):
    db, storage = live.app.state.db, live.app.state.storage
    talk = db.create_talk(title, "mic", "yue", "")
    storage.store_chunk(talk.id, 0, b"audio")
    db.set_audio_path(talk.id, str(storage.finalize(talk.id)))
    order = [Status.RECORDED, Status.TRANSCRIBING, Status.SUMMARISING, Status.DONE]
    if status is Status.FAILED:
        db.set_status(talk.id, Status.RECORDED)
        db.set_status(talk.id, Status.FAILED, error=error)
    else:
        for step in order[: order.index(status) + 1]:
            db.set_status(talk.id, step)
    db.add_segments(talk.id, list(segments))
    return talk


def test_library_lists_talks_newest_first_with_their_status(live_server, launch_browser):
    seed(live_server, "First talk")
    seed(live_server, "Second talk", status=Status.RECORDED)
    page = launch_browser()
    page.goto(f"{live_server.url}/library.html")

    page.wait_for_selector("#talks .talk")
    rows = page.locator("#talks .talk")
    assert rows.count() == 2
    assert "Second talk" in rows.nth(0).inner_text()
    assert "recorded" in rows.nth(0).inner_text()
    assert "First talk" in rows.nth(1).inner_text()
    assert "done" in rows.nth(1).inner_text()


def test_empty_library_says_so(live_server, launch_browser):
    page = launch_browser()
    page.goto(f"{live_server.url}/library.html")
    page.wait_for_selector("#empty:not([hidden])")


def test_clicking_a_talk_shows_its_transcript_and_audio_player(live_server, launch_browser):
    seed(live_server, "Keynote", segments=[(0.0, 4.0, "hello there"), (65.0, 70.0, "second line")])
    page = launch_browser()
    page.goto(f"{live_server.url}/library.html")
    page.click("text=Keynote")

    page.wait_for_selector(".line")
    lines = page.locator(".line")
    assert lines.count() == 2
    assert "00:00" in lines.nth(0).inner_text() and "hello there" in lines.nth(0).inner_text()
    assert "01:05" in lines.nth(1).inner_text()
    assert "Keynote" in page.inner_text("h1")
    assert page.get_attribute("audio", "src").endswith("/audio")
    assert page.get_attribute("audio", "preload") == "none"


def test_talk_page_updates_itself_while_the_talk_is_processed(live_server, launch_browser):
    talk = seed(live_server, "Busy talk", status=Status.TRANSCRIBING)
    page = launch_browser()
    page.goto(f"{live_server.url}/talk.html?id={talk.id}&poll_ms=200")
    page.wait_for_selector("#status:has-text('transcribing')")
    assert page.locator(".line").count() == 0

    db = live_server.app.state.db
    db.add_segments(talk.id, [(0.0, 3.0, "fresh words")])
    db.set_status(talk.id, Status.SUMMARISING)
    db.set_status(talk.id, Status.DONE)

    page.wait_for_selector("#status:has-text('done')", timeout=5000)
    page.wait_for_selector(".line:has-text('fresh words')")


def test_failed_talk_shows_the_error_and_a_retry_button(live_server, launch_browser):
    talk = seed(live_server, "Broken", status=Status.FAILED, error="RuntimeError: model missing")
    page = launch_browser()
    page.goto(f"{live_server.url}/talk.html?id={talk.id}&poll_ms=200")

    page.wait_for_selector("#error:not([hidden])")
    assert "model missing" in page.inner_text("#error")
    page.click("#retry")
    page.wait_for_selector("#status:has-text('recorded')", timeout=5000)
    assert live_server.app.state.db.get_talk(talk.id).status is Status.RECORDED


def test_recover_is_offered_only_after_the_recording_goes_quiet(live_server, launch_browser):
    db, storage = live_server.app.state.db, live_server.app.state.storage
    talk = db.create_talk("Crashed", "mic", "en", "")
    storage.store_chunk(talk.id, 0, b"partial")
    page = launch_browser()
    page.goto(f"{live_server.url}/talk.html?id={talk.id}&poll_ms=200")

    page.wait_for_selector("#status:has-text('recording')")
    page.wait_for_timeout(600)
    assert page.is_hidden("#recover")  # chunk just arrived: probably still recording

    part = next(storage.talk_dir(talk.id).glob("part-*"))
    old = time.time() - 300
    os.utime(part, (old, old))
    page.wait_for_selector("#recover:not([hidden])", timeout=5000)
    page.click("#recover")
    page.wait_for_selector("#status:has-text('recorded')", timeout=5000)
