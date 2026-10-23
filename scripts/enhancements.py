#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""PC enhancements made from the player's own CUSA03173 1.09 files at start.

Each one rewrites a few of the game's files into its own folder, which run.py lays under the
player's mods (mods.py --generated); switched off, the folder is not used and the game is as it
shipped. Every rewrite checks the dump's file and its own result by SHA-256, so an unexpected
dump leaves that file alone.

Ported from droogie's bbhost (https://github.com/droogie/bbhost, GPL-3.0-or-later):
engine/maiden_events.cpp and engine/dream_mirror_layout.cpp.

  pc_two_invaders       (BB_PC_TWO_INVADERS)  Mensis, Mergo's Loft, the Nightmare Frontier and
                                              the Old Hunters' areas hold two invaders, as the
                                              chalice dungeons do. Every player in a session
                                              needs it on.
  pc_mirror_appearance  (BB_PC_MIRROR)        the Hunter's Dream mirror opens the appearance
                                              editor (the developers' unused mirror character)

  pc_rebirth            (BB_PC_REBIRTH)       Rebirth in the Nightmare at the Altar of Despair:
                                              with the Yharnam Stone, level and attributes go back
                                              to the origin's and the echoes are refunded
                                              (src/rebirth.c does the runtime half)
  pc_enhanced_lamps     (BB_PC_LAMPS)         every lit lamp also offers Level Up and Storage, the
                                              game's own screens, once the Doll and the storage box
                                              have been used (enhanced_lamps.py). With Rebirth on,
                                              its altar edit shares the Nightmare's lamp archive.
  pc_boss_rematches     (BB_PC_REMATCHES)     EXPERIMENTAL (launcher toggle, off): Rematch a defeated
                                              boss at its own lamp, all 19 that have one
                                              (boss_rematches.py). Brings the lamps' menu with it;
                                              the permanent defeat flags and first-kill rewards are
                                              left alone.
  pc_menu               (BB_PC_MENU)          the in-game PC menu's assets (menu_assets.py): its
                                              sections in the options movie and its strings in
                                              every language. On by default: it only adds rows.
  pc_ebrietas_effect    (BB_PC_EBRIETAS_EFFECT) Ebrietas' trail effect as Nexus mod 41 ("SFX Fix")
                                              makes it: above 30 FPS her rock emitter never stops,
                                              the rocks pile up and the GPU is lost. On by default.

Rebirth's altar entries use message ids the PC menu's files add (pc_menu_messages.tsv).
"""
import argparse
import bisect
import hashlib
import os
from pathlib import Path
import shutil
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fromsoft import FormatError, dcx_compress, dcx_decompress  # noqa: E402

# ini key -> (environment override, folder name, label)
FEATURES = {
    'pc_two_invaders': ('BB_PC_TWO_INVADERS', 'two-invaders', 'Two invaders in the late areas'),
    'pc_mirror_appearance': ('BB_PC_MIRROR', 'dream-mirror', "Hunter's Dream mirror: change appearance"),
    'pc_rebirth': ('BB_PC_REBIRTH', 'rebirth', 'Rebirth in the Nightmare at the Altar of Despair'),
    # After Rebirth: both rewrite m24_02_00_00's talk archive, and the later layer wins (mods.py).
    'pc_enhanced_lamps': ('BB_PC_LAMPS', 'enhanced-lamps', 'Lamps: Level Up and Storage'),
    # After the lamps: its Central Yharnam talk archive adds the rematch to the lamp menu.
    'pc_boss_rematches': ('BB_PC_REMATCHES', 'boss-rematches', 'Boss rematches at their lamps (experimental)'),
    'pc_menu': ('BB_PC_MENU', 'pc-menu', 'In-game PC menu (System > PC Settings)'),
    'pc_ebrietas_effect': ('BB_PC_EBRIETAS_EFFECT', 'ebrietas-effect', "Ebrietas' trail effect (Nexus mod 41's fix)"),
}
# Off unless switched on, except these: the menu only adds rows, the Ebrietas effect avoids a crash.
DEFAULT_ON = {'pc_menu', 'pc_ebrietas_effect'}
# Still a first test: the launcher labels its toggle experimental; none in the overlay.
EXPERIMENTAL = {'pc_boss_rematches'}
# Bumped when a rewrite changes, so every install makes its files again.
VERSION = 'enhancements 5'  # 5: rematches for every boss with a lamp


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class Skip(Exception):
    """The dump's file is not the one a rewrite knows: the game keeps its own."""


# --- Two invaders (bbhost engine/maiden_events.cpp) ------------------------------------------
#
# A map's Chime Maiden rings while fewer invaders than allowed are in and a stop event ends her
# at the first one. Both test 3[29] (client count): its argument is [condition group s8][client
# type u8, 1 invader][comparison u8, 0 ==, 3 <, 4 >=][count u8]. "== 0" becomes "< 2" and ">= 1"
# becomes ">= 2"; two maps also start an event with another map's flag, which is corrected.
MAIDEN_MAPS = [
    # map, input sha256, output sha256, ring event, stop event, [(event, slot, index, was, now)]
    ('m26_00_00_00', '95d168643c0ca1e96d77577be2723dc15ad6af8588e729ca6ab76cd609bc9331',
     '4d84a87b673117ea2158ba7ccaa50ba22796bb2303b5d333121ea1dee8c1ec8b', 12604710, 12604720, []),
    ('m33_00_00_00', '9375a331f1727e6d1f89f233773af1ffdeaa1eba97f97e1122dc6fc83ee78ff4',
     '533f8409794420e62e1bcaea0f2297c85801e7cc04286a05d8e31a17d81e875c', 13304710, 13304720, []),
    ('m34_00_00_00', '61cbe85daf9097619094e053edcab1233432c86619b96198845d5469e917268c',
     '499cd490e24214f81f3fa1d50b459acd945a802574b09a7c9bfe74b883a24311', 13404710, 13404720,
     [(13404710, 5, 0, 3400701, 3400791)]),
    ('m35_00_00_00', '4989dfbe383c30e65847c1abfc5d8e09adea0b6caff11320f864069566e1e628',
     'e38558b6f8ebd80b07cdf16e4759e901c91922c687c9de59396e8d94773479af', 13504710, 13504720,
     [(13504700, 5, 2, 12604712, 13504712)]),
    ('m36_00_00_00', '9ea8f27a0e5b93884b528bbab79bc7da52a890aef07ae886f777df2450583639',
     'e257328d7eafad901c39575615e9b6d5e01251c3438a55ce49265757b1da820e', 13604710, 13604720, []),
]
RING_WAS, RING_NOW = bytes([1, 1, 0, 0]), bytes([1, 1, 3, 2])
STOP_WAS, STOP_NOW = bytes([0xff, 1, 4, 1]), bytes([0xff, 1, 4, 2])


def event_instructions(b, event_id):
    """(bank, id, argument offset, argument length) of each instruction of an event that has
    arguments. EMEVD (64-bit): header int64s at +0x10 - [0] events, [1] event table,
    [3] instruction table, [13] argument blob; events 0x30 bytes, instructions 0x20."""
    if len(b) < 0x90:
        return []
    events, event_at, ins_at, args_at = (struct.unpack_from('<q', b, o)[0] for o in (0x10, 0x18, 0x28, 0x78))
    out = []
    for e in range(events):
        ev = event_at + e * 0x30
        if ev + 0x30 > len(b) or struct.unpack_from('<q', b, ev)[0] != event_id:
            continue
        count, first = struct.unpack_from('<qq', b, ev + 8)
        for k in range(count):
            at = ins_at + first + k * 0x20
            if at + 0x20 > len(b):
                raise Skip('the event table runs past the file')
            bank, ins_id, length, offset = struct.unpack_from('<iiqq', b, at)
            if length:
                if args_at + offset + length > len(b):
                    raise Skip('an argument runs past the file')
                out.append((bank, ins_id, args_at + offset, length))
    return out


def two_invaders_map(emevd, rule):
    name, sha_in, sha_out, ring, stop, fixes = rule
    if sha256(emevd) != sha_in:
        raise Skip(f'{name}: not the 1.09 event script')
    out = bytearray(emevd)
    for event in (ring, stop):
        for bank, ins_id, at, length in event_instructions(out, event):
            if bank != 3 or ins_id != 29 or length < 4:
                continue
            if out[at:at + 4] == RING_WAS:
                out[at:at + 4] = RING_NOW
            elif out[at:at + 4] == STOP_WAS:
                out[at:at + 4] = STOP_NOW
    for bank, ins_id, at, length in event_instructions(out, 0):
        if bank != 2000 or ins_id != 0 or length < 8:
            continue
        slot, event = struct.unpack_from('<ii', out, at)
        for f_event, f_slot, index, was, now in fixes:
            field = at + 8 + 4 * index
            if (event, slot) == (f_event, f_slot) and field + 4 <= at + length \
                    and struct.unpack_from('<i', out, field)[0] == was:
                struct.pack_into('<i', out, field, now)
    if sha256(out) != sha_out:
        raise Skip(f'{name}: the rewrite came out unexpected')
    return bytes(out)


def two_invaders(dvdroot):
    files = {}
    for rule in MAIDEN_MAPS:
        relative = Path('event') / f'{rule[0]}.emevd.dcx'
        source = dvdroot / relative
        try:
            packed = source.read_bytes()
            files[relative] = dcx_compress(two_invaders_map(dcx_decompress(packed), rule), template=packed)
        except (OSError, FormatError, Skip) as error:
            print(f'Enhancements: two invaders: {rule[0]} keeps the game\'s maidens ({error})', file=sys.stderr)
    return files


# --- Hunter's Dream mirror (bbhost engine/dream_mirror_layout.cpp) ---------------------------
#
# m21_00_00_00.msb places ダミーCHR_再キャラメイク ("dummy character for re-making the character")
# at the workshop's mirror: entity 2100202, talk script t210696 ("Put on Disguise", then the
# appearance editor). The developers left it a DummyEnemy (type 10), which never spawns. As an
# Enemy (type 2) it spawns like the workbench dummy beside it. Parts are grouped by type in file
# order, so the entry moves from slot 807 to 742 and every field naming a part by slot follows.
MIRROR_IN = '8e1de0ee223cd5137a93383cfc7bb1d27964bc480c63e35013674717b403ef8f'
MIRROR_OUT = '99d5c7b7f52307344c6e8296b499d5e57969f21c443fcc607cb42cb2c38c8afa'
MOVE_FROM, MOVE_TO, FIRST_ENEMY = 807, 742, 736
ENEMY, DUMMY_ENEMY = 2, 10
EVENT_FIELDS = (0x48, 0x50, 0x5c)
PART_FIELDS = (0x128, 0x13c, 0x144, 0x178, 0x180, 0x188)


def msb_lists(b):
    """The MSB's MODEL, EVENT, POINT and PARTS lists: (offset table, [entry offsets])."""
    lists, at = [], 0x10
    for k in range(4):
        if at + 16 > len(b):
            raise Skip('the layout\'s lists do not read')
        count = struct.unpack_from('<i', b, at + 4)[0]
        table = at + 16
        if count < 1 or table + 8 * count > len(b):
            raise Skip('the layout\'s lists do not read')
        entries = [struct.unpack_from('<q', b, table + 8 * i)[0] for i in range(count - 1)]
        if any(e <= 0 or e >= len(b) for e in entries):
            raise Skip('the layout\'s lists do not read')
        lists.append((table, entries))
        at = struct.unpack_from('<q', b, table + 8 * (count - 1))[0]
        if k < 3 and not 0 < at < len(b):
            raise Skip('the layout\'s lists do not read')
    return lists


def remap(slot):
    if MOVE_TO <= slot < MOVE_FROM:
        return slot + 1
    return MOVE_TO if slot == MOVE_FROM else slot


def mirror_layout(msb):
    if sha256(msb) != MIRROR_IN:
        raise Skip('not the 1.09 m21_00_00_00 layout')
    b = bytearray(msb)
    lists = msb_lists(b)
    events, (parts_table, parts) = lists[1], lists[3]
    if len(parts) <= MOVE_FROM + 1:
        raise Skip('too few parts')
    starts = sorted(e for _, entries in lists for e in entries)

    def extent(entry):
        after = bisect.bisect_right(starts, entry)
        return (starts[after] if after < len(starts) else len(b)) - entry

    for entries, fields in ((events[1], EVENT_FIELDS), (parts, PART_FIELDS)):
        for e in entries:
            size = extent(e)
            for field in fields:
                if field + 4 > size:
                    continue
                value = struct.unpack_from('<i', b, e + field)[0]
                if value >= 0 and remap(value) != value:
                    struct.pack_into('<i', b, e + field, remap(value))
    for i, e in enumerate(parts):
        kind, index = struct.unpack_from('<ii', b, e + 0x14)
        if kind == ENEMY and i >= MOVE_TO:
            struct.pack_into('<i', b, e + 0x18, index + 1)
        if kind == DUMMY_ENEMY and i > MOVE_FROM:
            struct.pack_into('<i', b, e + 0x18, index - 1)
    moved = parts[MOVE_FROM]
    if struct.unpack_from('<i', b, moved + 0x14)[0] != DUMMY_ENEMY:
        raise Skip('the stand-in is not a DummyEnemy')
    struct.pack_into('<ii', b, moved + 0x14, ENEMY, MOVE_TO - FIRST_ENEMY)
    start, source, end = parts[MOVE_TO], parts[MOVE_FROM], parts[MOVE_FROM + 1]
    if not start < source < end:
        raise Skip('the parts are not in file order')
    size = end - source
    b[start:end] = b[source:end] + b[start:source]
    for i in range(MOVE_TO, MOVE_FROM):
        struct.pack_into('<q', b, parts_table + 8 * (i + 1), parts[i] + size)
    struct.pack_into('<q', b, parts_table + 8 * MOVE_TO, start)
    if sha256(b) != MIRROR_OUT:
        raise Skip('the rewrite is not the known result')
    return bytes(b)


def dream_mirror(dvdroot):
    relative = Path('map') / 'MapStudio' / 'm21_00_00_00.msb.dcx'
    try:
        packed = (dvdroot / relative).read_bytes()
        return {relative: dcx_compress(mirror_layout(dcx_decompress(packed)), template=packed)}
    except (OSError, FormatError, Skip) as error:
        print(f'Enhancements: Hunter\'s Dream mirror: the Dream keeps its layout ({error})', file=sys.stderr)
        return {}


# --- Rebirth in the Nightmare (bbhost engine/rebirth_script.cpp) -----------------------------
#
# t242307 (script/talk/m24_02_00_00.talkesdbnd.dcx) is the Altar of Despair's menu: "Offer
# Flesh To Altar" and "Do Nothing". A third entry, "Rebirth in the Nightmare", goes ahead of "Do
# Nothing": without the Yharnam Stone a message; with it the script sets REQ_RESET and waits for
# the port's runtime (src/rebirth.c) to reset the hunter to their origin's level and refund the
# echoes (FAIL set when it could not), opens the doll's level-up menu (MENU set until it has
# closed), then asks to accept or undo (REQ_UNDO). The four flags are unused by the game's
# scripts; the runtime clears them at every world load. The menu texts are the PC menu's
# (pc_menu_messages.tsv, group 30).
REBIRTH_IN = 'e56163a1bb8f46ae59368160e522e11f970e2268f6d356b823e4d72a7c969ff1'
REBIRTH_OUT = 'e726dec68e8d73c5d5b6ba1875fabd6a85320b6b14f95ca3d6729143a3c362b2'
REQ_RESET, REQ_UNDO, FAIL, MENU = 72500390, 72500391, 72500392, 72500393
YHARNAM_STONE = 4330
TEXT_OPTION, TEXT_NO_STONE, TEXT_FAIL, TEXT_ACCEPT, TEXT_UNDO = 14000332, 14000333, 14000334, 14000335, 14000336
BUILD_GROUP, HANDLE_GROUP = 2147483640, 2147483641  # fills the talk list / shows it and acts


def rebirth_script(data):
    import esd
    if sha256(data) != REBIRTH_IN:
        raise Skip('not the 1.09 t242307 (the Altar of Despair)')
    s = esd.parse(data)
    build, handle = s.group(BUILD_GROUP), s.group(HANDLE_GROUP)
    if not build or not handle:
        raise Skip("the altar's menu groups are missing")
    list_rest, choice, end = s.state_in(build, 3), s.state_in(handle, 1), s.state_in(handle, 6)
    if min(list_rest, choice, end) < 0:
        raise Skip("the altar's menu states are missing")
    EQ, REG0 = b'\x95', b'\xaf'

    def eq(lhs, rhs):
        return esd.done(lhs + esd.lit(rhs) + EQ)

    def cmd(id, args):
        return s.cmd(1, id, [esd.done(esd.lit(v)) for v in args])

    # The entry, ahead of "Do Nothing".
    rest = s.states[list_rest]
    rest.entry = s.run([cmd(19, [3, TEXT_OPTION, -1])] + s.runs[rest.entry].items)
    st = {}
    for id in range(7, 16):  # the new states, 7..15 of the handling group
        st[id] = s.state(id)
        handle.states.append(st[id])

    def set_state(state, conds=-1, entry=-1, whiles=-1):
        x = s.states[state]
        if conds >= 0:
            x.conds = conds
        if entry >= 0:
            x.entry = entry
        if whiles >= 0:
            x.whiles = whiles
    wait = s.cmd(1, 68, [b'\x81' + struct.pack('<d', 0.33) + b'\xa1'])  # the altar's own c1_68(0.33)
    truth = esd.done(esd.lit(1))
    dialog_closed = eq(esd.call(58, [0]), 0)
    # Chosen: the stone, or a message.
    set_state(st[7], s.run([s.cond(st[9], eq(esd.call(47, [3, YHARNAM_STONE, 5, 0, 0]), 1)), s.cond(st[8], truth)]))
    set_state(st[8], s.run([s.cond(end, dialog_closed)]), s.run([cmd(17, [7, TEXT_NO_STONE, 1, 0, 1])]))
    # The runtime's reset.
    set_state(st[9], s.run([s.cond(st[10], eq(esd.call(15, [REQ_RESET]), 0))]),
              s.run([cmd(11, [FAIL, 0]), cmd(11, [REQ_RESET, 1])]), s.run([wait]))
    set_state(st[10], s.run([s.cond(st[11], eq(esd.call(15, [FAIL]), 1)), s.cond(st[12], truth)]))
    set_state(st[11], s.run([s.cond(end, dialog_closed)]), s.run([cmd(11, [FAIL, 0]), cmd(17, [7, TEXT_FAIL, 1, 0, 1])]))
    # The level-up menu, until the runtime says it has closed.
    set_state(st[12], s.run([s.cond(st[13], eq(esd.call(15, [MENU]), 0))]), s.run([cmd(11, [MENU, 1]), s.cmd(1, 31, [])]))
    # Leaving it: accept or undo; closing the choice goes back to the menu.
    set_state(st[13], s.run([s.cond(st[14], truth)]),
              s.run([s.cmd(1, 20, []), cmd(19, [1, TEXT_ACCEPT, -1]), cmd(19, [2, TEXT_UNDO, -1])]))
    set_state(st[14],
              s.run([s.cond(end, esd.done(esd.lit(23) + b'\x84\xa7' + esd.lit(1) + EQ)),  # reg0 = f23(); == 1: accept
                     s.cond(st[15], eq(REG0, 2)),                                          # undo
                     s.cond(st[12], eq(esd.call(53, []), 0))]),                            # closed: back to the menu
              s.run([s.cmd(1, 76, [])]), s.run([wait]))
    set_state(st[15], s.run([s.cond(end, eq(esd.call(15, [REQ_UNDO]), 0))]), s.run([cmd(11, [REQ_UNDO, 1])]), s.run([wait]))
    # The choice: entry 3 goes to the new states, ahead of "Do Nothing / closed".
    old = s.runs[s.states[choice].conds].items
    s.states[choice].conds = s.run([old[0], s.cond(st[7], eq(REG0, 3))] + old[1:])
    out = esd.serialize(s)
    if sha256(out) != REBIRTH_OUT:
        raise Skip('the rewrite is not the known result')
    return out


def rebirth(dvdroot):
    from fromsoft import Bnd4
    relative = Path('script') / 'talk' / 'm24_02_00_00.talkesdbnd.dcx'
    try:
        packed = (dvdroot / relative).read_bytes()
        archive = Bnd4(dcx_decompress(packed))
        index = archive.index('t242307.esd')
        archive.files[index] = rebirth_script(archive.files[index])
        return {relative: dcx_compress(archive.to_bytes(), template=packed)}
    except (OSError, FormatError, Skip, ValueError) as error:
        print(f'Enhancements: Rebirth: the altar keeps its menu ({error})', file=sys.stderr)
        return {}


def enhanced_lamps(dvdroot, keys=(), rematches=None):
    """Level Up and Storage at every lit lamp. The Altar of Despair's archive holds lamps too:
    with Rebirth on, its altar script is rewritten here as well, so whichever layer is read the
    archive has both. rematches: the boss lamps' rematch entries (boss_rematches.lamp_rows)."""
    import enhanced_lamps as lamps
    try:
        files = lamps.make(dvdroot, rematches=rematches)
    except (OSError, FormatError, ValueError) as error:
        print(f'Enhancements: Lamps: the lamps keep their menus ({error})', file=sys.stderr)
        return {}
    shared = Path('script') / 'talk' / 'm24_02_00_00.talkesdbnd.dcx'
    if 'pc_rebirth' in keys and shared in files:
        from fromsoft import Bnd4
        try:
            archive = Bnd4(dcx_decompress(files[shared]))
            index = archive.index('t242307.esd')
            archive.files[index] = rebirth_script(archive.files[index])
            files[shared] = dcx_compress(archive.to_bytes(), template=(dvdroot / shared).read_bytes())
        except (OSError, FormatError, Skip, ValueError) as error:
            print(f'Enhancements: Lamps: the altar keeps its Rebirth entry off ({error})', file=sys.stderr)
    return files


def boss_rematches(dvdroot, keys=()):
    """Boss rematches at the bosses' own lamps (experimental). Its lamp archives are the lamps'
    own composition (with Rebirth's altar when that is on) with the rematch entries added."""
    import boss_rematches as rematches
    # The two invaders rewrite five of the same event files: with both on, the rematch edits go on
    # top of theirs, so whichever layer is read the maps have both.
    def with_invaders(data, rule):
        try:
            return two_invaders_map(data, rule)
        except Skip:  # the invaders' layer leaves this map alone too
            return data

    before = {}
    if 'pc_two_invaders' in keys:
        for rule in MAIDEN_MAPS:
            before[rule[0]] = lambda data, rule=rule: with_invaders(data, rule)
    try:
        files = rematches.make(dvdroot, before=before)
    except (OSError, FormatError, ValueError) as error:
        print(f'Enhancements: Boss rematches: not made ({error})', file=sys.stderr)
        return {}
    lamps = enhanced_lamps(dvdroot, keys, rematches.lamp_rows())
    if not lamps:
        print('Enhancements: Boss rematches: not made (the lamp menus could not be made)', file=sys.stderr)
        return {}
    files.update(lamps)
    return files


def pc_menu(dvdroot):
    import menu_assets
    return menu_assets.make(dvdroot, log=lambda line: print(f'Enhancements: {line}', file=sys.stderr))


# --- Ebrietas' trail effect (Awakenchan/BloodBorneButPc 0.9.37 beta 9, after Nexus mod 41) ------
# f001251720.fxr is replaced in her two effect binders by the Fishing Hamlet's f001454436.fxr.
EFFECT_NAME = 'f001251720.fxr'
EFFECT_SHA = '988c55ba0f689bc0b4f8e7a9f9b184ef8cd9bcd4601b2c925387ff5ce3fc9f0b'
EFFECT_SOURCE = (Path('sfx') / 'frpg_sfxbnd_m36.ffxbnd.dcx', 'f001454436.fxr',
                 '990644087f325191d34fd2f4b633a9f7c6a63ce9d71786c4289a7cae5cdfb4e0')
# binder, sha256 of it unpacked (1.09) and of the result unpacked
EFFECT_BINDERS = (
    (Path('sfx') / 'frpg_sfxbnd_m24_02.ffxbnd.dcx',
     'b0bd083145a753a667c4021a3f817879646b1f8b84201e2774daa17e1c5b0e99',
     'fae6b9639fb02b34188a3dd262b2695f7667812749f984f1eb2fd2ab298a9e9b'),
    (Path('sfx') / 'frpg_sfxbnd_m29a.ffxbnd.dcx',
     '085f2d3d60d54e50fa981c7aad89ca42f47b3a733a78b40ee98f572883ce122b',
     '8348b2b7f110feb7ca0a444e8331886b85fe24ba422b8b9909cdc5d551ffcb07'),
)
BND4_ENTRY = 0x24  # flags, -1, packed and unpacked size (i64), data offset (u32), id, name offset


def binder_entries(bnd):
    """(header offset, file name, data offset, size) of each file in an effect binder (BND4
    format 0x74: sizes, 32-bit offsets, ids, UTF-16 names)."""
    if bnd[:4] != b'BND4' or struct.unpack_from('<q', bnd, 0x20)[0] != BND4_ENTRY or bnd[0x30:0x32] != b'\x01\x74':
        raise Skip('unexpected effect binder layout')
    entries = []
    for i in range(struct.unpack_from('<i', bnd, 0x0c)[0]):
        at = 0x40 + i * BND4_ENTRY
        packed, unpacked, offset, _id, name_at = struct.unpack_from('<qqIii', bnd, at + 8)
        if packed != unpacked or offset + packed > len(bnd):
            raise Skip('unexpected effect binder entry')
        end = name_at
        while bnd[end:end + 2] != b'\0\0':
            end += 2
        name = bnd[name_at:end].decode('utf-16-le').replace('\\', '/').rsplit('/', 1)[-1]
        entries.append((at, name, offset, packed))
    return entries


def binder_file(bnd, name):
    found = [(offset, size) for _at, entry, offset, size in binder_entries(bnd) if entry == name]
    if len(found) != 1:
        raise Skip(f'{name} is not in the effect binder once')
    offset, size = found[0]
    return bnd[offset:offset + size]


def with_binder_file(bnd, name, data):
    """The binder with `name` holding `data`, appended 16-byte aligned; the other entries and the
    name table stay where they are."""
    at = next(at for at, entry, _offset, _size in binder_entries(bnd) if entry == name)
    offset = (len(bnd) + 15) & ~15
    out = bytearray(bnd) + bytes(offset - len(bnd)) + data
    struct.pack_into('<qqI', out, at + 8, len(data), len(data), offset)
    return bytes(out)


def ebrietas_effect(dvdroot):
    files = {}
    replacement = None
    for relative, input_sha, output_sha in EFFECT_BINDERS:
        try:
            packed = (dvdroot / relative).read_bytes()
            raw = dcx_decompress(packed)
            if sha256(raw) != input_sha:
                raise Skip('not the 1.09 file')
            if sha256(binder_file(raw, EFFECT_NAME)) != EFFECT_SHA:
                raise Skip(f'unexpected {EFFECT_NAME}')
            if replacement is None:
                source, source_name, source_sha = EFFECT_SOURCE
                replacement = binder_file(dcx_decompress((dvdroot / source).read_bytes()), source_name)
                if sha256(replacement) != source_sha:
                    raise Skip(f'unexpected {source_name}')
            result = with_binder_file(raw, EFFECT_NAME, replacement)
            if sha256(result) != output_sha:
                raise Skip('the rewrite is not the known result')
            files[relative] = dcx_compress(result, template=packed)
        except (OSError, FormatError, Skip) as error:
            print(f"Enhancements: Ebrietas' trail effect: {relative.name} left as it is ({error})", file=sys.stderr)
    return files


MAKERS = {'pc_two_invaders': two_invaders, 'pc_mirror_appearance': dream_mirror, 'pc_rebirth': rebirth,
          'pc_enhanced_lamps': enhanced_lamps, 'pc_boss_rematches': boss_rematches, 'pc_menu': pc_menu,
          'pc_ebrietas_effect': ebrietas_effect}
# Makers whose files depend on which other features are on (their stamp names those features).
COMBINED = {'pc_enhanced_lamps': ('pc_rebirth',), 'pc_boss_rematches': ('pc_rebirth', 'pc_two_invaders')}


def enabled(settings, env):
    """The features switched on: the environment overrides bbport.ini; both default to off."""
    on = []
    for key, (variable, _folder, _label) in FEATURES.items():
        value = env.get(variable, settings.get(key, '1' if key in DEFAULT_ON else '0'))
        if str(value).strip() == '1':
            on.append(key)
    return on


def read_settings(path):
    values = {}
    try:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip()
    except OSError:
        pass
    return values


def generator():
    """The generator's own identity: its version and the scripts and strings it runs."""
    here = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in ('enhancements.py', 'menu_assets.py', 'fromsoft.py', 'esd.py', 'enhanced_lamps.py',
                 'boss_rematches.py', 'emevd.py', 'pc_menu_messages.tsv'):
        try:
            digest.update((here / name).read_bytes())
        except OSError:
            pass
    return f'{VERSION} {digest.hexdigest()[:16]}'


def stamp_for(dvdroot, files, identity=None):
    """What a feature's folder was made from: the generator and the dump's source files."""
    lines = [identity or generator()]
    for relative in sorted(files):
        try:
            info = (dvdroot / relative).stat()
            lines.append(f'{relative.as_posix()} {info.st_size} {int(info.st_mtime)}')
        except OSError:
            lines.append(f'{relative.as_posix()} missing')
    return '\n'.join(lines) + '\n'


def make(game, out, keys):
    """Makes (or reuses) each feature's folder; returns those with files in them."""
    dvdroot = Path(game) / 'dvdroot_ps4'
    folders = []
    for key in keys:
        folder = Path(out) / FEATURES[key][1]
        stamp_file = folder / 'stamp.txt'
        with_others = [other for other in COMBINED.get(key, ()) if other in keys]
        identity = ' +'.join([generator(), *with_others])
        try:
            previous = stamp_file.read_text(encoding='utf-8')
        except OSError:
            previous = None
        if previous and previous.splitlines()[0] == identity:
            made = [Path(line.rsplit(' ', 2)[0]) for line in previous.splitlines()[1:]]
            if made and stamp_for(dvdroot, made, identity) == previous and \
                    all((folder / 'dvdroot_ps4' / m).is_file() for m in made):
                folders.append(folder)
                print(f'Enhancements: {FEATURES[key][2]} (up to date)', file=sys.stderr)
                continue
        files = MAKERS[key](dvdroot, keys) if key in COMBINED else MAKERS[key](dvdroot)
        shutil.rmtree(folder, ignore_errors=True)
        if not files:
            continue
        for relative, data in files.items():
            target = folder / 'dvdroot_ps4' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        stamp_file.write_text(stamp_for(dvdroot, files, identity), encoding='utf-8')
        folders.append(folder)
        print(f'Enhancements: {FEATURES[key][2]} ({len(files)} files)', file=sys.stderr)
    return folders


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--game', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--settings', type=Path)
    args = parser.parse_args()
    keys = enabled(read_settings(args.settings) if args.settings else {}, os.environ)
    for folder in make(args.game, args.out, keys):
        print(folder)


if __name__ == '__main__':
    main()
