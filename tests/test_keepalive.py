#!/usr/bin/env python3
import io
import time

import pytest


def test_keepalive_disabled_by_default(session):
    """No config, no session marker -- the default must be off."""

    assert session.config.get("keepalive", 0) == 0


def test_heartbeat_tick_skips_while_command_running(linux):
    """The per-tick check must refuse to send while a command owns the
    channel, even with keepalive enabled."""

    sent = []
    linux.platform.channel.send = lambda data: sent.append(data)
    linux.platform.command_running = object()

    linux.platform._heartbeat_tick()

    assert sent == []


def test_heartbeat_tick_skips_while_interactive(linux):
    """The per-tick check must refuse to send while live-interactive,
    so it never injects a byte into the user's terminal session."""

    sent = []
    linux.platform.channel.send = lambda data: sent.append(data)
    linux.platform._interactive = True

    linux.platform._heartbeat_tick()

    assert sent == []


def test_heartbeat_tick_sends_while_idle(linux):
    """When nothing is running and not interactive, a tick sends exactly
    one no-op byte."""

    sent = []
    linux.platform.channel.send = lambda data: sent.append(data)

    linux.platform._heartbeat_tick()

    assert sent == [b"\n"]


def test_heartbeat_live_reconfigure(linux):
    """Enabling keepalive on an already-connected session (not just at
    connect time) must take effect, since the poll loop re-reads the
    config every second rather than only once at startup."""

    sent = []
    real_send = linux.platform.channel.send

    def spy_send(data):
        sent.append(data)
        return real_send(data)

    linux.platform.channel.send = spy_send
    linux.config.set("keepalive", "1", glob=True)

    time.sleep(2.5)

    assert len(sent) >= 1


@pytest.mark.manager_config(
    args={"config": io.StringIO('set -g db "memory://"\nset -g keepalive 1\n')}
)
def test_heartbeat_survives_idle_period(linux):
    """With a real 1s heartbeat thread running, sitting idle for several
    intervals must not break the session."""

    time.sleep(3.5)

    output = linux.platform.run(
        "echo still-alive", shell=True, capture_output=True, text=True, check=True
    )
    assert output.stdout.strip() == "still-alive"


@pytest.mark.manager_config(
    args={"config": io.StringIO('set -g db "memory://"\nset -g keepalive 1\n')}
)
def test_heartbeat_does_not_corrupt_long_running_command(linux):
    """A command running longer than several heartbeat intervals must
    still complete with correct, uncorrupted output."""

    output = linux.platform.run(
        "sleep 0.5; echo done; sleep 2.5",
        shell=True,
        capture_output=True,
        text=True,
        check=True,
    )
    assert output.stdout.strip() == "done"
