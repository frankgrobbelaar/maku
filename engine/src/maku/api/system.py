"""What this PC has, and what Maku can do on it and how fast (maku/hardware.py, maku/pc_check.py):
for Setup's last step, About in Settings, Convert and Make English subtitles. Testing the PC
checks it again and times each part."""

from contextlib import closing
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status

from maku import db, hardware
from maku.api.common import ApiModel, Paths
from maku.core import hardware as decide
from maku.pc_check import PcCheck

router = APIRouter()

type Part = Literal["encoder", "subtitles"]
type Encoder = Literal["nvenc", "amf", "qsv"]


class Card(ApiModel):
    name: str  # as Windows names it: "NVIDIA GeForce GTX 1660 SUPER"
    maker: Literal["nvidia", "amd", "intel", "other"]
    memory: int | None  # bytes of its own; None when Windows doesn't say
    integrated: bool  # the processor's graphics, sharing the PC's memory
    driver: str | None  # its driver's version, as its maker writes it: "617.42"


class Ability(ApiModel):
    """One part of Maku on this PC."""

    part: Literal["convert", "subtitles", "player"]
    state: Literal["ready", "limited", "no"]
    how: str  # what does it here: "HEVC 10-bit on NVIDIA's encoder (NVENC)"
    note: str | None  # what's limited, or why it can't
    # An hour of video's time here: converting, 1080p's then 4K's; subtitles, Best's then Fast's.
    seconds: list[float]


class Places(ApiModel):
    """Where English subtitles of each quality are made here; None: not on this PC."""

    best: Literal["card", "processor"] | None
    fast: Literal["card", "processor"] | None
    # Why Best isn't on this PC: its card hasn't the memory, or doesn't run DirectX 12.
    best_wants: Literal["memory", "directx"] | None


class Measured(ApiModel):
    """How this PC's times were measured: by a test at `at`, or by the jobs since `at`."""

    at: str
    tested: bool
    conversions: int  # files converted since, each measuring its way again
    subtitles: int  # videos' subtitles made since


class Checking(ApiModel):
    """A check of this PC under way."""

    step: Part  # the part it's on
    done: list[Part]
    fps: float | None  # the encoder's frames a second making 1080p, once timed
    timing: bool  # it times each part; else only checks what runs


class System(ApiModel):
    graphics_card: str | None  # the card Maku works on, as Windows names it
    card: Card | None  # the card Maku works on: the dedicated one with the most memory
    cards: list[Card]
    processor: str | None  # "Intel Core i5-9600K"
    cores: int | None
    memory: int | None  # bytes installed
    checked_at: str | None  # when this PC was checked; None till it is
    encoder: Encoder | None  # what converts here; None without one
    # The card's maker's drivers, when its own encoder didn't start for want of a newer one.
    driver_link: str | None
    encoder_problem: str | None  # what that encoder said
    abilities: list[Ability]  # each part of Maku here, once it's checked
    subtitles: Places
    measured: Measured | None  # None while the times are a guess
    testing: Checking | None  # a check under way


def _pc(request: Request) -> PcCheck:
    pc: PcCheck = request.app.state.pc
    return pc


Pc = Annotated[PcCheck, Depends(_pc)]


@router.get("/system")
def this_pc(paths: Paths, pc: Pc) -> System:
    return _system(paths, pc)


@router.post("/system/test", status_code=status.HTTP_202_ACCEPTED)
def test_this_pc(paths: Paths, pc: Pc) -> System:
    """Checks this PC again and times each part, in the background (about a minute); unless a
    check is under way already."""
    if not pc.ready():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Maku tests this PC once ffmpeg is downloaded."
        )
    pc.test()  # a check under way already shows as it is
    return _system(paths, pc)


def _system(paths: Paths, pc: PcCheck) -> System:
    facts = pc.facts()
    with closing(db.connect(paths.database)) as conn:
        _, checked = hardware.stored(conn)
        speeds, rates = hardware.speeds(conn), hardware.rates(conn)
        measured = hardware.measured(conn)
    card = decide.best_card(facts.cards)
    places = decide.hearing_places(facts.cards, checked)
    abilities = decide.abilities(facts.cards, checked, speeds, rates) if checked else ()
    stopped = checked is not None and decide.driver_problem(checked.encoder_problem)
    testing = pc.testing()
    return System(
        graphics_card=card.name if card else None,
        card=_card(card) if card else None,
        cards=[_card(each) for each in facts.cards],
        processor=facts.processor,
        cores=facts.cores,
        memory=facts.memory,
        checked_at=checked.at if checked else None,
        encoder=cast("Encoder | None", checked.encoder if checked else None),
        driver_link=decide.DRIVERS.get(card.maker) if stopped and card else None,
        encoder_problem=checked.encoder_problem if checked else None,
        abilities=[
            Ability(
                part=each.part,
                state=each.state,
                how=each.how,
                note=each.note,
                seconds=list(each.seconds),
            )
            for each in abilities
        ],
        subtitles=Places(
            best=places["best"],
            fast=places["fast"],
            best_wants=None
            if places["best"]
            else ("directx" if checked and not checked.directml else "memory"),
        ),
        measured=Measured(
            at=measured.at,
            tested=measured.tested,
            conversions=measured.conversions,
            subtitles=measured.subtitles,
        )
        if measured
        else None,
        testing=Checking(
            step=testing.step, done=list(testing.done), fps=testing.fps, timing=testing.timing
        )
        if testing
        else None,
    )


def _card(card: decide.Card) -> Card:
    return Card(
        name=card.name,
        maker=card.maker,
        memory=card.memory,
        integrated=card.integrated,
        driver=card.driver,
    )
