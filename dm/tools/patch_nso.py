# Generic NSO rewriter: Switch aarch64 module → an image that can execute natively on Apple systems.
# Usage: patch_nso.py <NSO file> <output dir> <module name>
# Rewrites (the Apple kernel modifies x18 and tpidr_el0; Horizon's thread area, svc and timers have no counterpart on Apple):
#   x18 read/write      → thread slot K18 (TSD, via tpidrro_el0)
#   mrs tpidr_el0       → read thread slot KTLS; msr tpidr_el0 → write KTLS
#   mrs tpidrro_el0     → read thread slot KTLR (Horizon ThreadLocalRegion pointer)
#   svc #n, mrs cntpct_el0 → host gate (gate address taken from thread slot KGATE; once in C, gates.tsv is looked up by return point)
#   Registered cuts (CUTS, restricted by NSO build ID): before rewriting, the original bytes are asserted one by one and any mismatch aborts; results are listed in <name>.cuts.tsv
#   Registered observation gates (OBS, restricted by build ID): one instruction at the entry is replaced with "enter the host observation callback → execute the original instruction → jump back", so diagnostics modify zero code at runtime; listed in <name>.obs.tsv
# The key page only stores "actual key number × 8" at the end of the data segment, and patch code fetches thread slots indirectly through the key page: the loader may use any key number.
# Output: <name>.patched.bin (key page and patch area appended after the image at PATCH_OFF; when that would start beyond 112 MB the patch area sits before the base, see FAR), <name>.fixups.tsv (layout and key page index header), <name>.gates.tsv, <name>.sites.tsv, <name>.cuts.tsv, <name>.obs.tsv
import struct, re, sys, os
from itertools import combinations
import lz4.block
from capstone import *

src, outdir, NAME = sys.argv[1], sys.argv[2], sys.argv[3]
d = open(src, 'rb').read()
assert d[:4] == b'NSO0'
flags = struct.unpack_from('<I', d, 0xc)[0]
segs = [struct.unpack_from('<III', d, 0x10 + i * 0x10) for i in range(3)]
bss = struct.unpack_from('<I', d, 0x3c)[0]
csz = struct.unpack_from('<III', d, 0x60)
# Every jump between the patch area and the code is a B (±128 MB). A patch area appended after the image (with bss) cannot reach the code when it would start beyond 112 MB (leaving 16 MB for the patch area): Metroid Dread's main has about 1.8 GB of bss (the engine's static heap); Engage's main starts its patch area at about 103 MB and keeps it after the image.
# The patch area then sits FRONT bytes before the module base (PATCH_OFF is negative), and the output file holds only text + ro + data (FILE_IMAGE_LEN) followed by the patch area; the loader supplies zero pages for bss and the key page (IMAGE_SIZE is the whole image).
# The key page stays after bss (the patch area reaches it through ADRP, ±4 GB). Modules below the limit produce output byte-identical to before
NEAR_PATCH_OFF = ((((segs[2][1] + segs[2][2] + bss + 0x3FFF) & ~0x3FFF) + 0x4000 + 0xFFFF) & ~0xFFFF)   # where an appended patch area would start (as in the else branch below)
FAR, FRONT = NEAR_PATCH_OFF > 0x7000000, 0x2000000
# A text segment that ends within 32 MB of the ±128 MB reach (Monster Hunter Rise: 125.3 MB of text) puts the patch area right before the base instead. Its stubs follow the sites in address
# order, so the last site's stub ends up about as far from it as the text is long. The first pass tries the gap that keeps every site in reach; when the patch area does not fit there
# (Monster Hunter Rise: 3.6 MB), the rewriter runs again with exactly the size it needs (DM_PATCH_FRONT, set only by that rerun) and B() checks every branch
BIG_TEXT = FAR and segs[0][2] + FRONT > 0x8000000 - 0x10000
if BIG_TEXT: FRONT = int(os.environ.get('DM_PATCH_FRONT', '0'), 0) or (0x8000000 - 0x10000 - segs[0][2]) & ~0xFFFF
IMG = bytearray(segs[2][1] + segs[2][2] + (0 if FAR else bss))
for i, (fo, mo, sz) in enumerate(segs):
    raw = d[fo:fo + csz[i]]
    if flags >> i & 1: raw = lz4.block.decompress(raw, uncompressed_size=sz)
    IMG[mo:mo + sz] = raw
TEXT_END = segs[0][2]
RO_OFF, DATA_OFF = segs[1][1], segs[2][1]
if FAR:
    FILE_IMAGE_LEN = (len(IMG) + 0x3FFF) & ~0x3FFF
    KEY_PAGE_OFF = (len(IMG) + bss + 0x3FFF) & ~0x3FFF
    IMAGE_SIZE, PATCH_OFF = KEY_PAGE_OFF + 0x4000, -FRONT
else:
    KEY_PAGE_OFF = (len(IMG) + 0x3FFF) & ~0x3FFF
    IMG.extend(bytes(0x4000))
    PATCH_OFF = (len(IMG) + 0xFFFF) & ~0xFFFF

# ---- Registered cuts: {NSO build ID: [(offset, original bytes, new bytes, reason)]} ----
CUTS = {
  # Super Mario Odyssey 1.4.1 main (the same main build as 1.3.0). The sead perspective constructor already sets aspect to 4:3. al::Projection::set at 0x73de60 calls
  # PerspectiveProjection::set here, overwriting that aspect with the game's 16:9. Near / far and fovy are set again immediately afterwards (0x73de98 and 0x73debc),
  # so skipping this redundant set retains 4:3 without losing those values. This is the exact build / address used by Fayaz's SMO-AAR patch.py.
  # Must ship with display_aspect 4:3 and the matching layout RootPane correction; never stretch an uncorrected game's presentation alone.
  'b424be150a8e7d78701cbe7a439d9ebf': [
    (0x73de88, '1aa90894', '1f2003d5', '4:3 camera projection: retain sead constructor aspect; al::Projection sets near/far/FOV afterwards (SMO-AAR)'),
    # Title and pause menu without "Playing in VR" (part 6) and "Action Guide" (part 3). The menu maps its logical items to parts through
    # two tables (title 0xec8270, pause 0xec8288) and wraps the cursor at the count passed to main+0x1d6850. Both counts become 4 and the
    # tables keep Save/Options/VR (parts 4/5/6) in logical slots 2/4/5 for the special-mode deactivation there. The 2P checks that grey
    # out the VR slot (title logical 3, pause logical 2) would now hit Options/Save, so those calls go. Paired with the Menu layout
    # changes in tools/prepare_odyssey_aspect.py (hidden parts, closed-up positions); the decide handlers still test part numbers.
    (0x49723c, 'e1071f32', '81008052', 'title menu: 4 items (Resume, Resume 2P, New Game, Options)'),
    (0x497324, '77fef417', 'c0035fd6', 'title menu: drop the 2P VR-slot deactivate tail call (return value unused)'),
    (0x497334, '23fef417', 'c0035fd6', 'title menu: drop the 2P VR-slot activate tail call'),
    (0x49609c, 'e1071f32', '81008052', 'pause menu: 4 items (Continue, Two/One Player, Save, Options)'),
    (0x496138, 'f202f597', '1f2003d5', 'pause menu: drop the 2P VR-slot deactivate call'),
    (0x496164, '9702f597', '1f2003d5', 'pause menu: drop the 2P VR-slot activate call'),
    (0x4963f4, '4302f597', '1f2003d5', 'menu update: drop the per-frame 2P VR-slot deactivate call'),
    (0x4963fc, 'f101f597', '1f2003d5', 'menu update: drop the per-frame 2P VR-slot activate call'),
    (0xec8270, '000000000100000002000000060000000300000005000000', '000000000100000002000000050000000600000003000000',
     'title menu parts: Resume, Resume 2P, New Game, Options (unused tail: VR, Help)'),
    (0xec8288, '000000000100000006000000030000000400000005000000', '000000000100000004000000050000000500000006000000',
     'pause menu parts: Continue, Two/One Player, Save, Options (tail keeps Options/VR in logical 4/5)'),
  ],
  # Super Mario Bros. Wonder v0 main
  'cd6e42aee7934f4d8393cd43893ae25e': [
    # Resource heap slack: each resource unit's ExpHeap is created with the resource size table value + 0x1008 (main+0x1e603c → ExpHeap::create main+0x4aac38); the table holds Nintendo's measured peaks with almost no margin
    # (PlayerYoshiAnm uses 99%). On the host, Model/NpcCommonerA.bfres in the opening course Course900 is about 0x70 bytes short: after the model resource's last GPU chunk (MatBlock,
    # 0x9000 bytes, 4 KB aligned, main+0x4290c0) is placed, its 0x598-byte descriptor does not fit, the GPU allocation fails → a buffer is built on a null memory pool → null read crash at main+0x106f5c8.
    # Where this differs from hardware is not known (every allocation size before this block is determined by game code and data); for now every resource heap gets +16 KB.
    (0x1e62fc, 'e00317aa', 'e0124091', 'resource heap size: mov x0,x23 → add x0,x23,#0x4000 (ExpHeap::create size argument +16 KB)'),
  ],
  # Super Mario Bros. Wonder 1.2.1 (v327680) main: same as above. Location carried over from v0 by dm/tools/nso_fnmap.py (containing function 0x1e603c → 0x1cf6f0 identical after address masking, ExpHeap::create 0x4aac38 → 0x4c4a18)
  'ff773e90972d544eb79406eaa65396d5': [
    (0x1cf9b0, 'e00317aa', 'e0124091', 'resource heap size: mov x0,x23 → add x0,x23,#0x4000 (ExpHeap::create size argument +16 KB)'),
  ],
  # Fire Emblem Engage 2.0.0 (v327680) main: run the game's own 60 fps path (vertical sync count always 1).
  # The game's time class App.GameTime picks a vertical sync count per scene (Slow = 2, i.e. 30 fps: system, movies, demos, combat cutscenes, the hub; Normal is 1 only when GameConfig.IsPerformance)
  # and hands it to Unity through GameTime.SetVsyncCount(int) (QualitySettings.vSyncCount → NVN present interval). About 96 pieces of per-frame logic (cameras, map cursor, unit actors, menu scrolling and cursors, hub camera, minigames)
  # step by GameTime.VsyncFixedCount (= vSyncCount, how many 60 Hz ticks each frame advances): with a count of 2 and 60 frames on screen they all run twice as fast, with a count of 1 at 60 fps they are right.
  # The real-time VsyncDeltaCount / VsyncDeltaTime (hub character movement, fishing, dragon ride and so on, about 120 places) do not depend on the frame rate.
  # The cut is in Unity's managed wrapper QualitySettings.set_vSyncCount (main+0x32f92c0): both paths use w19 as the argument, mov w19,w0 → mov w19,#1,
  # so every caller (GameTime, QualitySettingsStack.PopImpl, XRSystem) can only set 1; the read side (get_vSyncCount) follows at 1 and the game stays consistent. No code calls SetQualityLevel.
  '8c08b9719e085f91847b5e0f935d9488': [
    (0x32f92d4, 'f303002a', '33008052', 'QualitySettings.set_vSyncCount wrapper: argument mov w19,w0 → mov w19,#1 (the 60 fps path of the game itself)'),
  ],
  # The Legend of Zelda: Breath of the Wild 1.9.0 (v1114112) main: 60 fps. The main loop of sead::GameFrameworkNx (main+0x112660c) runs a dynamic interval (framework +0x267 = 1):
  # every frame it computes how many vsyncs the last frame needed (rounded up), clamped to [2, max 3] (the max comes from the interval controller +0xc, constructed at main+0x1126c04); it steps up after 3 overrunning frames in a row,
  # steps down one level every 6 frames until 2, and hands the result through setWaitVsyncInterval (vtable +0x130, main+0x11269b8) to presentation (nvnWindowSetPresentInterval).
  # The game logic time step follows it: ksys::VFR is initialized with a base interval of 2 (constant 2 at main+0x127e740 → VFR::init main+0x151d2d0), and every frame VFR::updateInterval (main+0x151d3d0,
  # called at main+0xcf9ad4 / main+0x1281044) takes the framework's current interval (vtable +0x138); the frame ratio = current interval / 2 -- at interval 1 each frame advances half a 30 fps tick and the game speed stays the same;
  # when it struggles and steps back to 2 / 3 the ratio is 1 / 1.5, again at the same speed. So only the floor changes from 2 to 1: the lower bound of the candidate interval (two places), the step-down target recorded when stepping up, max(candidate, 3) - 1 → max(candidate, 2) - 1,
  # and stepping down stops at < 3 → < 2. On hardware the same logic starting from 1 would also be 60 fps; it falls back to 30 by itself only when its input shows a slow frame (the last two cuts make that input include the GPU time).
  # With the frame step (FRAME_STEP below) the host's step replaces the controller's interval, except while the game's own VFR override is set (and at fps_target 0): the framework then keeps the controller's
  'cd57b23fa4bbad65803d9788c01821ee': [
    (0x112670c, '6041201e', '4041201e', 'lower bound of the candidate interval: fmov s0,s11 (2.0) → fmov s0,s10 (1.0)'),
    (0x1126710, '7f0b0071', '7f070071', 'lower bound of the candidate interval: cmp w27,#2 → cmp w27,#1'),
    (0x112665c, '78008052', '58008052', 'step-down target recorded when stepping up, max(candidate, w24) − 1: mov w24,#3 → mov w24,#2'),
    (0x1126748, '1f0d0071', '1f090071', 'step-down target recorded when stepping up: cmp w8,#3 → cmp w8,#2'),
    (0x1126794, '3f0d0071', '3f090071', 'stepping down stops at < 3 → at < 2: cmp w9,#3 → cmp w9,#2'),
    # The controller's input (framework +0x250, controller main+0x1126cec..) is the main thread's CPU span up to the draw step (about 2.7 ms in the first shrine), so GPU-bound frames stayed at interval 1 and the game ran slow
    # (iPhone 16 Pro Max: 25 ms frames, two thirds of the speed). The game has a GPU-time path that uses max(CPU span, GPU time between the frame's two timestamp reports, framework +0x220, read after the fence wait)
    # but takes it only while [main+0x1e3a638]+0x1d2b8 is set (64 of 6,046 shrine frames); both of its checks become branches into it. The GPU time needs the profile's gpu_timestamps segment
    (0x112691c, 'c00000b4', '03000014', 'interval controller always takes the GPU time path (CPU span timing): cbz x0,#0x1126934 → b #0x1126928'),
    (0x1126974, 'c00000b4', '03000014', 'interval controller always takes the GPU time path (takes max(CPU span, GPU time)): cbz x0,#0x112698c → b #0x1126980'),
  ],
  # Fire Emblem Engage 2.0.0 (v327680) sdk: AddressRegionManager node area 0x3fe00000 (about 1 GB) → 0x3e00000 (62 MB).
  # The constructor (sdk+0x346420) carves the node area out of the start of the alias region (a unit heap of 0x30-byte nodes, mapped only as used) before AllocateAddressRegion hands out regions.
  # The hardware alias region is 64 GB, so the 1 GB does not matter there; the host's alias region is only 5.375 GB (iOS caps a single reservation at 6 GB), and after StandardAllocator's 3.14 GB block (1 GB aligned)
  # Unity's low-level virtual allocator (main+0x9aa0f4 → AllocateAddressRegion) had only about 1.2 GB left; about 357 s into the prologue battle it got no region → returned 0 → null write crash at main+0x9a4664.
  # 62 MB holds about 1.35 million nodes (a few hundred regions are live in measurements). Both movs must change together: +0x346430 sets the node area limit, +0x3464cc registers it as an occupied region.
  '56ec24747ec9e7f19b3efb062483a19d': [
    (0x346430, '08fca752', '087ca052', 'AddressRegionManager constructor: node area limit mov w8,#0x3fe00000 → mov w8,#0x3e00000'),
    (0x3464cc, '09fca752', '097ca052', 'AddressRegionManager constructor: length of the node area registered as an occupied region mov w9,#0x3fe00000 → mov w9,#0x3e00000'),
  ],
  # Ace Attorney Investigations Collection 1.0.0.2 (v131072) sdk (SDK 17.5.3): the same node area cut as Engage's. Without it nninitStartup's StandardAllocator::Initialize(nullptr, pool − used)
  # (main+0x874b6c, virtual address memory) aborts at its first CentralHeap::Init: the 1 GB-aligned region of 3.14 GB did not fit in the 4.375 GB alias region after the node area.
  # The constructor is at sdk+0x139458 (limit = alias start + 0x3fe00000 at +0x28, a unit heap of 0x30-byte nodes, the area then registered as occupied)
  '311deab1f062b504f3d646a49ddcd4e8': [
    (0x139468, '08fca752', '087ca052', 'AddressRegionManager constructor: node area limit mov w8,#0x3fe00000 → mov w8,#0x3e00000'),
    (0x1394fc, '09fca752', '097ca052', 'AddressRegionManager constructor: length of the node area registered as an occupied region mov w9,#0x3fe00000 → mov w9,#0x3e00000'),
  ],
  # Pokémon Legends: Z-A 2.0.2 (v393216) sdk (SDK 19.3.11): the same node area cut. The constructor is at sdk+0x1423ec (limit = alias start + 0x3fe00000 at +0x28, a unit heap of 0x30-byte
  # nodes, the area then registered as occupied at +0x142468). With main's allocator region below, the guest block fits the 5 GB proven on a phone
  'df7a3960c74c3a4803f826c587153252': [
    (0x1423fc, '08fca752', '087ca052', 'AddressRegionManager constructor: node area limit mov w8,#0x3fe00000 → mov w8,#0x3e00000'),
    (0x142468, '09fca752', '097ca052', 'AddressRegionManager constructor: length of the node area registered as an occupied region mov w9,#0x3fe00000 → mov w9,#0x3e00000'),
  ],
  # Pokémon Legends: Z-A 2.0.2 (v393216) main: nninitStartup (main+0x1b2e650) initializes its StandardAllocator with virtual address memory over 12 GB of address space (main+0x1b3e3e4), which
  # the Switch's 64 GB alias region holds and an iPhone's single 6 GB reservation cannot. The allocator commits pages as it goes and the pool (3.2 GB) bounds what it maps (profile mem_map_limit);
  # its largest block is nninitStartup's own probe of pool − used (3.15 GB, allocated and freed at once), so 4 GB of address space holds it
  'b1f12fd919eae86ab8a978317677e64b': [
    (0x1b3e3e4, '6200c0d2', '2200c0d2', 'StandardAllocator::Initialize(nullptr, size): address space mov x2,#0x300000000 → mov x2,#0x100000000 (12 GB → 4 GB)'),
  ],
  # The Legend of Zelda: Link's Awakening 1.1.0 (v131072) main: the physics step (main+0x15730, main thread) rebuilds each world's PhysX completion task in place
  # (a PxLightCpuTask at world+0xc8) and passes it to simulate. A worker runs it (main+0x10ccf80: fetchResults, world+0x1d8 done = 1, notify, unlock) and then calls its
  # release (main+0x10cd070), which calls the task's own destructor: vtable back to the PxLightCpuTask base, mTm = 0 (main+0x10cced0). At 30 fps the game steps twice
  # per frame (step, wait, step, wait); the unlock hands the world's mutex to the woken main thread, and when the worker is descheduled there the main thread's
  # next step rebuilds the task before the late destructor runs, which then wipes the new task. The next simulation's NpSceneCompletion::release reads its mTm = 0:
  # crash at main+0x10ccf28 (lr main+0x13c236c; seen on the iPhone and in 2 of 5 Mac runs, in every Mac run under CPU load). On the Switch the release follows the
  # unlock within nanoseconds. The release becomes a plain ret: the destructor only resets the vtable and mTm (no resources), the step rebuilds every field, and this
  # release is used by this one vtable (main+0x1c51308 slot 7) only
  '909e904af78ac1b8deefe97ab2ccdb51': [
    (0x10cd070, '080040f9', 'c0035fd6', 'physics completion task release (calls its own destructor): ldr x8,[x0] → ret (no longer destroyed; the step function rebuilds it in place every step)'),
  ],
  # Fire Emblem: Three Houses 1.2.0 (v327680) main: 60 fps. KTGL runs the game on the main thread at 60 updates a second whatever it shows: each update steps by
  # 1/fps with fps = 60.0 (main+0x1a38f08, set at main+0x50e114; dt at main+0x510010), and the frame end (main+0x50f680) waits out 60/fps ticks of 1/59.94 s in a yield loop
  # (main+0x5be430). The render thread (main+0x50f8c0) draws the latest update and presents with the interval of the render mode (frame +0xbb84, set at main+0x50f3d0:
  # 0 = 1080p docked, 2 = 720p handheld; 3 / 5 their two-view variants; 1 and 4 are 720p / 1080p modes at interval 1 that nothing selects). Measured on the Mac: 59.2 updates
  # and 29.8 presents a second. The per-mode interval table (int at main+0xd13de0, read by main+0x4b0420 for the present and by the 6-tick fade counter in main+0x4b7530;
  # float at main+0xd13e40, the per-frame scroll step in main+0x4c2b30) becomes 1 for every mode, as in modes 1 and 4: every update is shown and the render thread's
  # own steps stay at the same speed. Resolutions stay per mode
  '89048449ba238c8cf565518b83bf02d3': [
    (0xd13de0, '020000000100000002000000020000000100000002000000', '010000000100000001000000010000000100000001000000', 'per-render-mode present interval table {2,1,2,2,1,2} → all 1 (60 fps; the game logic already runs at 60 updates a second)'),
    (0xd13e40, '000000400000803f00000040000000400000803f00000040', '0000803f0000803f0000803f0000803f0000803f0000803f', 'per-render-mode interval as float {2.0,1.0,2.0,2.0,1.0,2.0} → all 1.0 (render-thread per-frame steps)'),
    # The render thread still presents with interval 2 while either of two flags is set: main+0x21c9a03, a full-screen image drawn before the frame (main+0x4b4908: the opening movie),
    # and frame +0xc55f / +0xc560 (from the object at app +0x40: the character creation screen after the movie, and so on). In the engine's own 60 fps modes this traded 60 fps for
    # resolution in those scenes (main+0x50f7d0 drops 720p mode 1 to 1080p mode 0); here it would show them at 30 with the render thread's own steps at half speed. Both are ignored
    (0x50fb7c, '2801082a', 'e8031f2a', 'render thread forced interval 2: orr w8,w9,w8 (either flag) → mov w8,wzr (the mode\'s interval, 1)'),
    # The frame limiter's wait (main+0x5be430: yield, read the tick, until 60/fps ticks of 1/59.94 s have passed since the last frame end; x8 = time passed and x23 = target, in 100 ns)
    # is a busy loop on the host: the yield back-off spins its first 2 ms on a performance core and then oversleeps by up to 250 µs, so frames took 16.8 ms (59.5 fps, a repeated
    # display frame every 2 s) and CPU energy went from 0.16 W at 30 fps to 1.5 W on the Mac. The yield becomes nn::os::SleepThread of 96% of the time left, and the loop goes back to
    # the limiter's own tick read and comparison at main+0x5be44c (the instructions after the b are no longer reached); the host's sleep never oversleeps, so the frames take 16.68 ms
    (0x5be4c0, '20fa1494', 'e00208cb', 'frame limiter wait: bl YieldThread → sub x0,x23,x8 (time left, 100 ns units)'),
    (0x5be4c4, 'bbf71494', '01e87bd3', 'frame limiter wait: bl GetSystemTick → lsl x1,x0,#5'),
    (0x5be4c8, '680240f9', '2018008b', 'frame limiter wait: ldr x8,[x19] → add x0,x1,x0,lsl #6 (96 ns per 100 ns left)'),
    (0x5be4cc, '080008cb', '8df71494', 'frame limiter wait: sub x8,x0,x8 → bl nn::os::SleepThread (PLT main+0xafc300)'),
    (0x5be4d0, '087d149b', 'dfffff17', 'frame limiter wait: mul x8,x8,x20 → b main+0x5be44c (read the tick and compare again)'),
    # The render thread waits for the next update with KTGL's event wait (main+0xaa90e0, timeout in µs: × 1000 → nn::os::TimedWaitEvent) and passes 1/fps × 1000 = 16, one frame in ms,
    # so it polls every 16 µs: at 60 fps it draws in about 3 ms and then polled for the rest of the frame (42,000–53,000 wakeups a second on the Mac, against 1,200 at 30 fps, where
    # it waited in the present instead). The other four callers wait without a timeout. The timeout becomes 1000/fps × 1000 = 16,666 µs (s8 = 1000.0, loaded first)
    (0x50f8e8, '01102e1e', '483d0090', 'render thread wait timeout: fmov s1,#1.0 → adrp x8,#0xcb7000'),
    (0x50f8ec, '2018201e', '08514bbd', 'render thread wait timeout: fdiv s0,s1,s0 → ldr s8,[x8,#0xb50] (1000.0)'),
    (0x50f8f0, '483d0090', '0019201e', 'render thread wait timeout: adrp x8,#0xcb7000 → fdiv s0,s8,s0 (1000/fps; the fmul by s8 that follows makes it µs)'),
    (0x50f8f4, '08514bbd', '1f2003d5', 'render thread wait timeout: ldr s8,[x8,#0xb50] → nop (moved up)'),
  ],
  # Hyrule Warriors: Age of Calamity 1.3.0 (v327680) main: the init (main+0x8d9610) hands the KTSL sound engine three heaps carved from one block: 15 MB engine memory, 2 MB, and
  # 142 MB sound data (sizes built by mov x8,#0xf00000; movk x8,#0x20,lsl #48 and mov w9,#0x8e00000; constructor main+0x12647a0, heaps created at main+0x1a2ba58). The audio renderer
  # work buffer in the 15 MB heap is 0x760000 (the SDK's AudioRenderSystem::GetWorkBufferSize, 0x40a9c8 of it command buffer), and the engine's setup asks for about 16.9 MB in
  # all: the fourth 0x1b5860-byte player block (main+0x1a32f70; three of the four players mix 5.1) came back null, the setup released its memory pools and gave up (-51),
  # the first sound archive (ASRS) never loaded and nnMain's resource wait (main+0x8d9bc8) spun forever. Where hardware differs is not known. The engine heap gets 4 MB from the
  # sound data heap, so the block the three come from keeps its size
  'c3cf52bf2b05d7310884971b50bcccb8': [
    (0x8d9610, '081ea0d2', '0826a0d2', 'sound engine heap: mov x8,#0xf00000 → mov x8,#0x1300000 (+4 MB)'),
    (0x8d9618, '091ca152', '0914a152', 'sound data heap: mov w9,#0x8e00000 → mov w9,#0x8a00000 (-4 MB; the block the three heaps come from keeps its total size)'),
  ],
  # Octopath Traveler 0 1.0.5 (v327680) main: Unreal's nninitStartup (main+0x12d74) constructs the engine allocator, an FMallocBinned3, in place at main+0x68022c8 (main+0x12e40 → constructor
  # main+0x9f480). Its constructor reserves 37 GB of address space (main+0x9f748: 74 pools of 512 MB, pool index = offset >> 29), which only the Mac can give: an iPhone has about 5 GB without the
  # extended virtual addressing entitlement, and the pools are too uneven to shrink (at character creation the largest holds 68 MB, the 74 together 732 MB). The constructor is not called;
  # the host puts its own allocator's vtable in the object instead (dm/host/hle_uemalloc.c: Malloc, Realloc, Free and the size queries on a host malloc zone), and every allocation goes through it
  # (FMemory reaches the object through FPlatformMemory::BaseAllocator, main+0x132b4, and the thread-local storage allocator nninitStartup registers, main+0x12e80 / main+0x12ec0, through its vtable)
  '9fe60a212cff9b9a3656ab63d4f882e5': [
    (0x12e40, '90310294', '1f2003d5', 'nninitStartup: bl 0x9f480 (FMallocBinned3 constructor, 37 GB of address space) → nop; the host allocator is in the object already (hle_uemalloc.c)'),
  ],
  # Octopath Traveler 0 1.0.5 (v327680) sdk (SDK 19.3.13): the AddressRegionManager node area 0x3fe00000 → 0x3e00000 (62 MB), as Engage's SDK 12 (above). The same constructor (sdk+0x1423ec): +0x1423fc
  # sets the node area limit, +0x142468 registers it as an occupied region. Unreal's region (-SwitchVirtualAddressSpaceSize, the profile's game_args) then starts 62 MB into the alias region, and the guest
  # block stays small enough for an iPhone next to the Unreal heap (hle_uemalloc.c), which lives outside it
  '7bba185a35ee9b4d0af66a4df910a823': [
    (0x1423fc, '08fca752', '087ca052', 'AddressRegionManager constructor: node area limit mov w8,#0x3fe00000 → mov w8,#0x3e00000'),
    (0x142468, '09fca752', '097ca052', 'AddressRegionManager constructor: length of the node area registered as an occupied region mov w9,#0x3fe00000 → mov w9,#0x3e00000'),
  ],
}
# ---- Registered observation gates: {NSO build ID: [(offset, number, original instruction word, reason)]}. Numbers match OBS_* in the host's hle.h;
# the original instruction must be position independent (no PC-relative / branch / anything involving x18 or tpidr), asserted offline; when the host has no callback attached the gate block goes in and out once and returns ----
OBS = {
  # Odyssey 1.4.1: set's post-fovy point carries its projection in x19;
  # AL calcMtx carries its full AL object in x0. Do not hook generic sead getters:
  # their smaller PerspectiveProjection objects have no AL frustum extensions.
  'b424be150a8e7d78701cbe7a439d9ebf': [
    (0x73de9c, 21, '1e2c1008', 'live projection after setFovy; x19 is al::Projection'),
    (0x73da10, 22, 'a9be4ff4', 'al::Projection calcMtx entry; full typed AL object in x0'),
  ],
  # Metroid Dread 2.1.0 main: the movie player posts "link / unlink holders" requests into the dispatcher thread's request ring (main+0x222cc8) and goes on without waiting for them (after an unlink it frees the wrapper object and builds a new one in place).
  # On hardware the dispatcher thread (priority 30, core 0 only) preempts the main thread (priority 44, core 0) at once and finishes first; the host waits for the ring to empty after each post (hle_movie.c movie_ring_wait). The gates sit on the add x22, x22, #8 after the bl
  '646761f643afebb379edd5e6a5151af2': [
    (0x2247a4, 19, '910022d6', 'link request posted (loop at main+0x224728, x19 = request ring): wait for the dispatcher; orig add x22, x22, #8'),
    (0x2248e4, 20, '910022d6', 'unlink request posted (loop at main+0x224868, x19 = request ring): wait for the dispatcher before the object is freed; orig add x22, x22, #8'),
  ],
}
BUILD_ID = d[0x40:0x50].hex()
cuts = list(CUTS.get(BUILD_ID, []))
for off, ob, nb, why in cuts:
    ob, nb = bytes.fromhex(ob), bytes.fromhex(nb)
    assert len(ob) == len(nb) and IMG[off:off + len(ob)] == ob, f'cut original bytes mismatch {off:#x}: {bytes(IMG[off:off + len(ob)]).hex()}'
    IMG[off:off + len(nb)] = nb
# Key page indices are fixed; the key page content is written by the loader as "actual key number × 8".
KEYS = {'K18': 508, 'KTLS': 509, 'KTLR': 510, 'KGATE': 511}
KEY_INDEX = {k: i for i, k in enumerate(('K18', 'KTLS', 'KTLR', 'KGATE'))}

md = Cs(CS_ARCH_ARM64, CS_MODE_ARM); md.detail = True
patch = bytearray(); fix = []; gates = []; stats = {}
def stat(k): stats[k] = stats.get(k, 0) + 1
def here(): return PATCH_OFF + len(patch)
def emit(w, kind=None):
    if kind: fix.append((len(patch), kind))
    patch.extend(struct.pack('<I', w & 0xFFFFFFFF))

def emit_key_addr(reg, kind):
    fix.append((len(patch), kind)); emit(ADRP(reg, here(), KEY_PAGE_OFF)); emit(LDRX(reg, reg, KEY_INDEX[kind]))

def emit_slot_addr(base, key_reg, kind):
    emit_key_addr(key_reg, kind); emit(ADDR(base, base, key_reg))

# ---- Encoders ----
def B(frm, to):
    off = to - frm; assert -(1 << 27) <= off < (1 << 27) and off % 4 == 0
    return 0x14000000 | ((off >> 2) & 0x3FFFFFF)
def STP(t, t2, n, off): return 0xA9000000 | (((off // 8) & 0x7F) << 15) | (t2 << 10) | (n << 5) | t
def LDP(t, t2, n, off): return 0xA9400000 | (((off // 8) & 0x7F) << 15) | (t2 << 10) | (n << 5) | t
def STP_PRE(t, t2, n, off): return 0xA9800000 | (((off // 8) & 0x7F) << 15) | (t2 << 10) | (n << 5) | t
def LDP_POST(t, t2, n, off): return 0xA8C00000 | (((off // 8) & 0x7F) << 15) | (t2 << 10) | (n << 5) | t
def STUR(t, n, off): return 0xF8000000 | ((off & 0x1FF) << 12) | (n << 5) | t   # stur xt,[xn,#off] (off may be negative)
def LDUR(t, n, off): return 0xF8400000 | ((off & 0x1FF) << 12) | (n << 5) | t   # ldur xt,[xn,#off]
def LDRX(t, n, imm12=0): return 0xF9400000 | (imm12 << 10) | (n << 5) | t
def STRX(t, n, imm12=0): return 0xF9000000 | (imm12 << 10) | (n << 5) | t
def MRS_TPIDRRO(t): return 0xD53BD060 | t
def ADRP(dd, pc, target):
    imm = ((target & ~0xFFF) - (pc & ~0xFFF)) >> 12; assert -(1 << 20) <= imm < (1 << 20)
    return 0x90000000 | ((imm & 3) << 29) | (((imm >> 2) & 0x7FFFF) << 5) | dd
def ADDI(dd, n, imm12, sh=0): return 0x91000000 | (sh << 22) | (imm12 << 10) | (n << 5) | dd
def ADDR(dd, n, m): return 0x8B000000 | (m << 16) | (n << 5) | dd
def SUBI(dd, n, imm12, sh=0): return 0xD1000000 | (sh << 22) | (imm12 << 10) | (n << 5) | dd
def BR(n): return 0xD61F0000 | (n << 5)
def CMPR(n, m): return 0xEB00001F | (m << 16) | (n << 5)   # cmp xn, xm (subs xzr)
def BEQ(frm, to):
    off = to - frm; assert -(1 << 20) <= off < (1 << 20) and off % 4 == 0
    return 0x54000000 | (((off >> 2) & 0x7FFFF) << 5)
def BRK(imm): return 0xD4200000 | ((imm & 0xFFFF) << 5)
def BLR(n): return 0xD63F0000 | (n << 5)
NOP = 0xD503201F

def dis(w, addr):
    l = list(md.disasm(struct.pack('<I', w), addr)); assert len(l) == 1, hex(w)
    return l[0]
def regset(ins):
    r, w = ins.regs_access()
    return {ins.reg_name(x) for x in r}, {ins.reg_name(x) for x in w}
def num(name):
    m = re.fullmatch(r'[xw](\d+)', name or ''); return int(m.group(1)) if m else None
def has18(ins): return re.search(r'\b[xw]18\b', ins.op_str) is not None
def regs_in(ins):
    s = {int(n) for n in re.findall(r'\b[xw](\d+)\b', ins.op_str)}
    try:
        rd, wr = regset(ins); s |= {num(n) for n in rd | wr} - {None}
    except Exception: pass
    return s
def pick(avoid, n=2):
    out = [r for r in range(0, 16) if r not in avoid and r != 18][:n]; assert len(out) == n; return out

def subst(ins, S):
    """x18/w18 → xS/wS: only the 4 register field positions are changed, verified against the disassembly text."""
    w = struct.unpack('<I', ins.bytes)[0]
    want = re.sub(r'\b([xw])18\b', lambda m: f'{m.group(1)}{S}', ins.op_str)
    pos = [p for p in (0, 5, 10, 16) if (w >> p) & 31 == 18]
    for k in range(len(pos), 0, -1):
        for c in combinations(pos, k):
            nw = w
            for p in c: nw = (nw & ~(31 << p)) | (S << p)
            try: dd = dis(nw, ins.address)
            except AssertionError: continue
            if dd.mnemonic == ins.mnemonic and dd.op_str == want: return nw
    raise RuntimeError(f'subst fail {ins.address:x} {ins.mnemonic} {ins.op_str}')

# ---- Rewrite blocks of each kind ----
def sp_delta(ins):
    """The amount an instruction writes back to sp (pre-index [sp, #i]! / post-index [sp], #i); returns 0 if sp is not written back."""
    m = re.search(r'\[sp, #(-?(?:0x)?[0-9a-f]+)\]!', ins.op_str)
    if m: return int(m.group(1), 0)
    m = re.search(r'\[sp\], #(-?(?:0x)?[0-9a-f]+)$', ins.op_str)
    if m: return int(m.group(1), 0)
    assert not re.match(r'(sp|wsp),', ins.op_str), f'writes sp: {ins.address:x} {ins.op_str}'
    return 0

def site_plain(ins):
    S, T = pick(regs_in(ins))
    dlt = sp_delta(ins)
    save = -16 if dlt == 0 else -112          # Instructions that modify sp write below sp, so the scratch save is placed deep in the reserved area
    assert dlt == 0 or dlt >= -96, f'sp delta {dlt} at {ins.address:x}'
    start = here()
    emit(STP(S, T, 31, save)); emit(MRS_TPIDRRO(T)); emit_slot_addr(T, S, 'K18'); emit(LDRX(S, T))
    emit(subst(ins, S))
    emit(STRX(S, T))                 # Always write back: capstone can miss reporting a write (the adds w18 instance)
    emit(LDP(S, T, 31, save - dlt)); emit(B(here(), ins.address + 4))
    return start

def site_sp(ins):
    """Destination is sp and a source is x18 (Engage's alloca: mov x18, sp; sub x18, x18, x0; mov sp, x18). site_plain saves its scratch relative to the old sp and would restore it relative to the new one:
    copy the old sp into T first, and after the instruction restore S / T relative to T (without writeback, ldp may use the base register as a destination). x18 is not written, so the slot is not written back"""
    S, T = pick(regs_in(ins))
    start = here()
    emit(STP(S, T, 31, -16)); emit(MRS_TPIDRRO(T)); emit_slot_addr(T, S, 'K18'); emit(LDRX(S, T))
    emit(ADDI(T, 31, 0))             # mov T, sp (in add immediate, 31 is sp)
    emit(subst(ins, S))
    emit(LDP(S, T, T, -16)); emit(B(here(), ins.address + 4))
    return start

def site_cond(ins):
    w = struct.unpack('<I', ins.bytes)[0]
    S, T = pick(regs_in(ins))
    tgt = ins.operands[-1].imm
    start = here()
    emit(STP(S, T, 31, -16)); emit(MRS_TPIDRRO(T)); emit_slot_addr(T, S, 'K18'); emit(LDRX(S, T))
    m = ins.mnemonic
    taken = here() + 4 * 3
    off = (taken - here()) >> 2
    nw = ((w & 0xFF000000) | ((off & 0x7FFFF) << 5) | S) if m in ('cbz', 'cbnz') else ((w & 0xFFF80000) | ((off & 0x3FFF) << 5) | S)
    pc = here(); emit(nw)
    dd = dis(nw, pc); assert dd.mnemonic == m and dd.operands[-1].imm == taken
    emit(LDP(S, T, 31, -16)); emit(B(here(), ins.address + 4))
    assert here() == taken
    emit(LDP(S, T, 31, -16)); emit(B(here(), tgt))
    return start

def site_pcrel(ins):
    tgt = ins.operands[1].imm
    S, T = pick(set())
    start = here()
    emit(STP(S, T, 31, -16)); emit(MRS_TPIDRRO(T)); emit_slot_addr(T, S, 'K18')   # S first serves as a temporary for the key page offset; the next instruction then loads the target value
    pc = here(); emit(ADRP(S, pc, tgt))
    if ins.mnemonic == 'adr': emit(ADDI(S, S, tgt & 0xFFF))
    emit(STRX(S, T))
    emit(LDP(S, T, 31, -16)); emit(B(here(), ins.address + 4))
    return start

def site_br(ins, base, count):
    """Jump table br x18: target = base + 4i. Stash x16 in the red zone → equally spaced landing pads → restore x16 → original target."""
    start = here()
    emit(STUR(16, 31, -16)); emit(STUR(17, 31, -24))   # x16 / x17 are temporary registers that can stay live within a function; save them to the red zone before borrowing
    emit(MRS_TPIDRRO(16)); emit_slot_addr(16, 17, 'K18'); emit(LDRX(16, 16)); emit(LDUR(17, 31, -24))
    padbase = start + 4 * 24
    delta = padbase - base
    op = ADDI if delta >= 0 else SUBI; dl = abs(delta)
    ops = []; hi, lo = dl >> 12, dl & 0xFFF
    while hi: h = min(hi, 0xFFF); ops.append(op(16, 16, h, 1)); hi -= h
    if lo: ops.append(op(16, 16, lo, 0))
    assert len(ops) <= 12
    for o in ops: emit(o)
    emit(BR(16))
    while here() < padbase: emit(NOP)
    tails = padbase + 4 * count
    for i in range(count): emit(B(here(), tails + 8 * i))
    for i in range(count):
        emit(0xF85F0000 | (31 << 5) | 16)      # ldur x16,[sp,#-16]
        emit(B(here(), base + 4 * i))
    return start

def site_br_tab(ins, targets):
    """Offset-table br x18 (ldrsw x18,[xB,x18,lsl #2]; add x18,x18,xB): target = table base + signed entry; the table is constant, so all targets are read at rewrite time.
    x16 = guest x18, compared with each target in turn (adrp + add put the target address in x17); on a match restore x16 / x17 and jump to the original target; no match → brk (the original bounds check already stops out-of-range indices)"""
    start = here()
    emit(STUR(16, 31, -16)); emit(STUR(17, 31, -24))   # as in site_br: save x16 / x17 to the red zone before borrowing
    emit(MRS_TPIDRRO(16)); emit_slot_addr(16, 17, 'K18'); emit(LDRX(16, 16))
    uniq = sorted(set(targets))
    pads = here() + 4 * (4 * len(uniq) + 1)
    for k, t in enumerate(uniq):
        emit(ADRP(17, here(), t)); emit(ADDI(17, 17, t & 0xFFF)); emit(CMPR(16, 17)); emit(BEQ(here(), pads + 12 * k))
    emit(BRK(0x18))
    for t in uniq:
        emit(LDUR(16, 31, -16)); emit(LDUR(17, 31, -24)); emit(B(here(), t))
    return start

def site_blr(ins):
    """blr x18 (Engage main+0x9ff324): x16 = guest x18, x30 = the instruction after the original blr, br x16. At a call site x16 / x17 are intra-procedure-call temporaries under the calling convention, so they need no saving;
    the return address is the original one, so the callee returns straight there (IL2CPP's C++ exceptions look up unwind tables by return address and must not stop in the patch area)"""
    start = here()
    emit(MRS_TPIDRRO(16)); emit_slot_addr(16, 17, 'K18'); emit(LDRX(16, 16))
    ret = ins.address + 4
    emit(ADRP(30, here(), ret)); emit(ADDI(30, 30, ret & 0xFFF)); emit(BR(16))
    return start

def site_br_call(ins):
    """br x18 as an indirect tail call (tail_call): x16 = guest x18, br x16. As at site_blr, x16 / x17 are intra-procedure-call temporaries at a call, and x30 keeps the caller's return address"""
    start = here()
    emit(MRS_TPIDRRO(16)); emit_slot_addr(16, 17, 'K18'); emit(LDRX(16, 16)); emit(BR(16))
    return start

def site_sysreg_read(ins, kind):
    """mrs xN, tpidr_el0 / tpidrro_el0 → xN = thread slot value."""
    N = ins.bytes[0] & 31
    tmp = 16 if N != 16 else 17
    start = here()
    emit(STUR(tmp, 31, -16)); emit(MRS_TPIDRRO(N)); emit_slot_addr(N, tmp, kind); emit(LDRX(N, N)); emit(LDUR(tmp, 31, -16))   # tmp is saved by borrowing the red zone
    emit(B(here(), ins.address + 4))
    return start

def site_tpidr_write(ins):
    N = struct.unpack('<I', ins.bytes)[0] & 31
    (T,) = pick({N}, 1)
    start = here()
    emit(0xF81F0000 | (31 << 5) | T)           # stur xT,[sp,#-16]
    tmp = next(x for x in (16, 17) if x not in (N, T))
    emit(STUR(tmp, 31, -24)); emit(MRS_TPIDRRO(T)); emit_slot_addr(T, tmp, 'KTLS'); emit(STRX(N, T)); emit(LDUR(tmp, 31, -24))
    emit(0xF85F0000 | (31 << 5) | T)           # ldur xT,[sp,#-16]
    emit(B(here(), ins.address + 4))
    return start

def emit_gate_call():
    """Common section of a gate block (right after stp x29,x30,[sp,#-16]! and before blr x30): x30 = the gate address in thread slot KGATE.
        Fetching the slot through the key page needs a second register to be borrowed; x29 is borrowed and then immediately restored from the stack: the x29 saved by _dm_gate must be
        the guest's original value, since the crash backtrace walks the x29 chain."""
    emit(MRS_TPIDRRO(30)); emit_slot_addr(30, 29, 'KGATE'); emit(LDRX(30, 30)); emit(LDRX(29, 31))

def site_gate(ins, kind, arg):
    """svc / mrs cntpct_el0 → host gate. The gate address is taken from thread slot KGATE; the gate looks up gates.tsv by return point (the address of this block's ldp)."""
    start = here()
    emit(STP_PRE(29, 30, 31, -16))
    emit_gate_call()
    emit(BLR(30))
    ret = here()
    emit(LDP_POST(29, 30, 31, 16))
    emit(B(here(), ins.address + 4))
    gates.append((ret, kind, arg, ins.address))
    return start

def site_obs(off, oid, word):
    """Observation gate: original entry instruction → enter the host gate (arg = observation number) → restore x29/x30 → execute the original instruction → jump back to off+4.
        The first half of the gate block is word-for-word isomorphic with site_gate; the host only reads registers and does not modify them (the x0–x8 written back by dm_gate are the original values)."""
    ins = dis(word, off)
    assert ins.mnemonic not in ('adr', 'adrp', 'b', 'bl', 'br', 'blr', 'ret', 'cbz', 'cbnz', 'tbz', 'tbnz') and not ins.mnemonic.startswith('b.') \
        and not (ins.mnemonic.startswith('ldr') and '[' not in ins.op_str) and not has18(ins), f'observation gate original instruction cannot be relocated {off:#x} {ins.mnemonic} {ins.op_str}'
    start = here()
    emit(STP_PRE(29, 30, 31, -16))
    emit_gate_call()
    emit(BLR(30))
    ret = here()
    emit(LDP_POST(29, 30, 31, 16))
    emit(word)
    emit(B(here(), off + 4))
    gates.append((ret, 'obs', oid, off))
    return start

# ---- Exclusive windows ----
EXCL_LD = ('ldxr', 'ldaxr', 'ldxp', 'ldaxp', 'ldxrb', 'ldaxrb', 'ldxrh', 'ldaxrh')
EXCL_ST = ('stxr', 'stlxr', 'stxp', 'stlxp', 'stxrb', 'stlxrb', 'stxrh', 'stlxrh')
def find_windows(insl):
    out = []
    for i, ins in enumerate(insl):
        if ins.mnemonic not in EXCL_LD: continue
        j = i
        while j < len(insl) and insl[j].mnemonic not in EXCL_ST: j += 1
        if j >= len(insl) or j - i >= 16: continue
        # Another exclusive load before the store: this one has no store of its own (a retry block, see retry_block); spanning both would merge two sequences
        # (Tears of the Kingdom main+0x5a4674: ldxr w18; cmp; b.eq <stxr of 0x5a427c>; ...; 0x5a469c: ldxr w13; and; stxr; cbnz, a loop other code branches to)
        if any(x.mnemonic in EXCL_LD for x in insl[i + 1:j]): continue
        if j + 1 < len(insl) and insl[j + 1].mnemonic in ('cbz', 'cbnz'): j += 1
        seg = insl[i:j + 1]
        if any(has18(x) for x in seg): out.append(seg)
    return out

def site_window(seg):
    used = set()
    for x in seg: used |= regs_in(x)
    S, T = pick(used)
    lo, hi = seg[0].address, seg[-1].address + 4
    start = here()
    emit(STP(S, T, 31, -16)); emit(MRS_TPIDRRO(T)); emit_slot_addr(T, S, 'K18'); emit(LDRX(S, T))
    copy0 = here(); n = len(seg)
    # Exit stubs: the first stub right after the window must be the fall-through one (after the last window instruction, hi); targets of branches leaving the window come after it.
    # Previously the fall-through stub came last: as soon as a window contains a conditional branch out (e.g. ldxr; cmp; b.ne out; stxr; cbnz), a successful stxr fell into the
    # first branch-out stub, i.e. took the "compare not equal" path (SMBW main 0x81c40: the enqueue retried forever, the tail index filled up without storing a single task, and the job system hung). D2R's windows had no branch out, so it never hit this.
    exits = copy0 + 4 * n + 16
    ex_targets = []; words = []
    for k, x in enumerate(seg):
        w = struct.unpack('<I', x.bytes)[0]
        if has18(x): w = subst(x, S)
        m = x.mnemonic
        if m in ('cbz', 'cbnz', 'tbz', 'tbnz') or m.startswith('b.'):
            tgt = x.operands[-1].imm
            if lo <= tgt < hi: newt = copy0 + (tgt - lo)
            else: ex_targets.append(tgt); newt = exits + 16 * (len(ex_targets) - 1)
            pc = copy0 + 4 * k; off = (newt - pc) >> 2
            if m in ('tbz', 'tbnz'): w = (w & 0xFFF8001F) | ((off & 0x3FFF) << 5)
            else: w = (w & 0xFF00001F) | ((off & 0x7FFFF) << 5)
            dd = dis(w, pc); assert dd.operands[-1].imm == newt and dd.mnemonic == m
        else:
            assert m not in ('adr', 'adrp', 'b', 'bl', 'br', 'blr', 'ret') and not (m == 'ldr' and '[' not in x.op_str), hex(x.address)
        words.append(w)
    for w in words: emit(w)
    for t in [hi] + ex_targets:   # fall-through first
        emit(STRX(S, T)); emit(LDP(S, T, 31, -16)); emit(B(here(), t)); emit(NOP)
    return start, lo, hi

def retry_block(insl, k, wseg):
    """The branch insl[k] lands in the middle of window wseg. Accepted only when it ends an out-of-line retry block that re-enters the window at its store-exclusive:
    an exclusive load, then instructions that do not branch, then this branch. Tears of the Kingdom main+0x18598: ldxr w17,[x10]; cmp w15,w17; b.eq 0x181fc,
    where 0x181fc is the stxr w17,w18,[x10] of the window 0x181ec..0x18200, whose failed stxr branches back to 0x18598 (same shape at 0x185e8 → 0x18244).
    Returns (the retry block, the window from that store on), or None"""
    t = insl[k].operands[-1].imm
    tail = [y for y in wseg if y.address >= t]
    if not tail or tail[0].mnemonic not in EXCL_ST: return None
    for p in range(k - 1, max(-1, k - 8), -1):
        q = insl[p]
        if q.mnemonic in EXCL_LD: return insl[p:k + 1], tail
        if q.mnemonic in ('b', 'bl', 'br', 'blr', 'ret', 'cbz', 'cbnz', 'tbz', 'tbnz') or q.mnemonic.startswith('b.') or q.mnemonic in EXCL_ST: return None
    return None

def site_retry_window(parts):
    """A retry block (see retry_block) gets a patch copy of its own: it cannot jump into the window's copy, because the x18 stand-in would have to be loaded
    between its exclusive load and the store. parts = [(retry block, its fall-through), (window from the store on, the window's fall-through)] are copied one
    after the other under one prologue, each followed by its fall-through stub; branches to any copied instruction (between the parts, and the failed store's
    branch back to the retry block's head) stay inside the copy, every other target leaves through an exit stub as in site_window"""
    used = set()
    for seg, _ in parts:
        for x in seg: used |= regs_in(x)
    S, T = pick(used)
    start = here()
    emit(STP(S, T, 31, -16)); emit(MRS_TPIDRRO(T)); emit_slot_addr(T, S, 'K18'); emit(LDRX(S, T))
    pos, at = {}, here()
    for seg, _ in parts:
        for x in seg: pos[x.address] = at; at += 4
        at += 16
    exits, ex_targets = at, []
    for seg, ft in parts:
        for x in seg:
            w = struct.unpack('<I', x.bytes)[0]
            if has18(x): w = subst(x, S)
            m, pc = x.mnemonic, here()
            if m in ('cbz', 'cbnz', 'tbz', 'tbnz') or m.startswith('b.'):
                tgt = x.operands[-1].imm
                if tgt not in pos and tgt not in ex_targets: ex_targets.append(tgt)
                newt = pos[tgt] if tgt in pos else exits + 16 * ex_targets.index(tgt)
                off = (newt - pc) >> 2
                if m in ('tbz', 'tbnz'): w = (w & 0xFFF8001F) | ((off & 0x3FFF) << 5)
                else: w = (w & 0xFF00001F) | ((off & 0x7FFFF) << 5)
                dd = dis(w, pc); assert dd.operands[-1].imm == newt and dd.mnemonic == m
            else:
                assert m not in ('adr', 'adrp', 'b', 'bl', 'br', 'blr', 'ret') and not (m == 'ldr' and '[' not in x.op_str), hex(x.address)
            emit(w)
        emit(STRX(S, T)); emit(LDP(S, T, 31, -16)); emit(B(here(), ft)); emit(NOP)
    for t in ex_targets:
        emit(STRX(S, T)); emit(LDP(S, T, 31, -16)); emit(B(here(), t)); emit(NOP)
    return start

# ---- Function boundaries (eh_frame_hdr) ----
m0 = struct.unpack_from('<I', IMG, 4)[0]
assert IMG[m0:m0 + 4] == b'MOD0'
ehs = m0 + struct.unpack_from('<i', IMG, m0 + 16)[0]
def rd(o, enc):
    fmt, app = enc & 0xF, enc & 0x70
    v, sz = {0x3: (struct.unpack_from('<I', IMG, o)[0], 4), 0xB: (struct.unpack_from('<i', IMG, o)[0], 4),
             0x4: (struct.unpack_from('<Q', IMG, o)[0], 8)}[fmt]
    if app == 0x10: v += o
    if app == 0x30: v += ehs
    return v, sz
_, penc, cenc, tenc = IMG[ehs:ehs + 4]
o = ehs + 4
_, s = rd(o, penc); o += s
nfde, s = rd(o, cenc); o += s
starts = set()
for _ in range(nfde):
    a, s = rd(o, tenc); o += s
    _, s = rd(o, tenc); o += s
    starts.add(a)
starts = sorted(x for x in starts if x < TEXT_END)

# ---- Linear scan to find all rewrite points (not relying on register read/write reports) ----
kinds = {}
for o in range(0, TEXT_END, 4):
    w = struct.unpack_from('<I', IMG, o)[0]
    if w & 0xFFE0001F == 0xD4000001: kinds[o] = ('svc', (w >> 5) & 0xFFFF); continue
    if w & 0xFFFFFFE0 == 0xD53BD040: kinds[o] = ('tpidr_r', None); continue
    if w & 0xFFFFFFE0 == 0xD51BD040: kinds[o] = ('tpidr_w', None); continue
    if w & 0xFFFFFFE0 == 0xD53BD060: kinds[o] = ('tpidrro_r', None); continue
    if w & 0xFFFFFFE0 == 0xD53BE020: kinds[o] = ('cntpct', w & 31); continue
    if w & 0xFFFFFFE0 == 0xD53BE040: kinds[o] = ('cntvct', w & 31); continue
    # mrs xN, ctr_el0 (cache type): the Apple kernel does not expose it to user mode (SIGILL); SDK 16's nn::os::FlushDataCache reads it for the cache line size
    if w & 0xFFFFFFE0 == 0xD53B0020: kinds[o] = ('ctr', w & 31); continue
    for ins in md.disasm(IMG[o:o + 4], o):
        if has18(ins): kinds[o] = ('x18', None)

# Take the instruction table per function, find the windows and jump tables
import bisect
def func_of(a):
    i = bisect.bisect_right(starts, a) - 1
    return (starts[i], starts[i + 1] if i + 1 < len(starts) else TEXT_END) if i >= 0 else (a, a + 4)
done = set(); windows = []; jumps = {}; tabjumps = {}; tailcalls = set(); retries = []
def jump_offsets(insl, j):
    """The br x18 is preceded by the offset-table form (Engage main+0x12eec94): cmp w18,#N; b.hi; ldrsw x18,[xB,x18,lsl #2]; add x18,x18,xB.
    The index may be another register, and the bounds check may be on a register copied into it: Link's Awakening's GLSLC (subsdk0+0x1be6e8) has
    sub w0,w18,#0xd1; cmp w0,#0x31; b.hi; ldrsw x18,[x17,x0,lsl #2], its movie module (subsdk1+0xae9a4) cmp w21,#7; b.hi; ...; mov w18,w21; ldrsw x18,[x4,x18,lsl #2].
    The entry may also be loaded into another register and only the add writes x18: Cuphead (Unity 2017.4, main+0x1bb872c) has cmp w17,#7; ldrsw x17,[x15,x17,lsl #2]; add x18,x17,x15
    (found by armyja, GitHub pull request #1).
    For the table base xB, search back for the nearest writer: it must be add xB,xB,#lo, and the writer before it must be adrp xB. Returns all targets, or None if not recognized"""
    ctx = insl[max(0, j - 16):j]
    add = next((p for p in reversed(ctx) if p.mnemonic == 'add' and re.fullmatch(r'x18, x\d+, x\d+', p.op_str)), None)
    if not add: return None
    _, t, rb = add.op_str.split(', ')   # t = the loaded entry, rb = the table base
    ld = next((p for p in reversed(ctx) if p.mnemonic == 'ldrsw' and re.fullmatch(rf'{t}, \[{rb}, x(\d+), lsl #2\]', p.op_str)), None)
    if not ld: return None
    # GLSLC subsdk0+0x2f403c checks a masked copy instead: and w16,w18,#0x3f; cmp w16,#0xe; b.hi; ...; and x18,x18,#0x3f; ldrsw x18,[x15,x18,lsl #2]
    idx = {'w' + re.fullmatch(rf'{t}, \[{rb}, x(\d+), lsl #2\]', ld.op_str).group(1)}
    masked = None   # (source, mask, position) when the index is "source & mask"
    k0 = ctx.index(ld); cmp = None
    def wname(r): return 'w' + r[1:]
    for i in range(k0 - 1, -1, -1):   # walk back from the load: follow register copies into the index, stop at the bounds check
        p = ctx[i]
        m = re.fullmatch(r'(w\d+), (w\d+)', p.op_str) if p.mnemonic == 'mov' else None
        if m and m.group(1) in idx: idx.add(m.group(2)); continue
        m = re.fullmatch(r'([wx]\d+), ([wx]\d+), #(0x[0-9a-f]+|\d+)', p.op_str) if p.mnemonic == 'and' else None
        if m and wname(m.group(1)) in idx and masked is None: masked = (wname(m.group(2)), int(m.group(3), 0), i); continue
        m = re.fullmatch(r'(w\d+), #(0x[0-9a-f]+|\d+)', p.op_str) if p.mnemonic == 'cmp' else None
        if not m: continue
        if m.group(1) in idx: cmp = p; break
        if masked:   # the checked register must be "the same source & the same mask", with the source unchanged up to the index's and
            for q in range(i - 1, -1, -1):
                w = [wname(ctx[q].reg_name(r)) for r in ctx[q].regs_access()[1]]
                if m.group(1) not in w: continue
                mm = re.fullmatch(r'([wx]\d+), ([wx]\d+), #(0x[0-9a-f]+|\d+)', ctx[q].op_str) if ctx[q].mnemonic == 'and' else None
                if mm and wname(mm.group(2)) == masked[0] and int(mm.group(3), 0) == masked[1] and \
                   not any(masked[0] in [wname(ctx[z].reg_name(r)) for r in ctx[z].regs_access()[1]] for z in range(q + 1, masked[2])):
                    cmp = p
                break
            if cmp: break
    if not cmp: return None
    n = int(cmp.op_str.split('#')[1], 0) + 1
    k = insl.index(ld); lo = page = None
    for p in reversed(insl[max(0, k - 256):k]):   # the writer chain of the table base
        _, w = p.regs_access()
        if not any(p.reg_name(r) == rb for r in w): continue
        if lo is None and p.mnemonic == 'add' and re.fullmatch(rf'{rb}, {rb}, #(0x[0-9a-f]+|\d+)', p.op_str): lo = int(p.op_str.split('#')[1], 0); continue
        if lo is not None and p.mnemonic == 'adrp' and p.op_str.startswith(rb + ','): page = p.operands[1].imm
        break
    if page is None: return None
    tb = page + lo
    return [tb + struct.unpack_from('<i', IMG, tb + 4 * i)[0] for i in range(n)]
def table_base(insl, k, rb):
    """Address the table-base register rb holds at insl[k]: its writer chain before k must be add rb,rb,#lo after adrp rb (as in jump_offsets); None otherwise"""
    lo = None
    for p in reversed(insl[max(0, k - 256):k]):
        _, w = p.regs_access()
        if not any(p.reg_name(r) == rb for r in w): continue
        if lo is None and p.mnemonic == 'add' and re.fullmatch(rf'{rb}, {rb}, #(0x[0-9a-f]+|\d+)', p.op_str): lo = int(p.op_str.split('#')[1], 0); continue
        if lo is not None and p.mnemonic == 'adrp' and p.op_str.startswith(rb + ','): return p.operands[1].imm + lo
        return None
    return None
def jump_adr_offsets(insl, j):
    """Entries relative to an adr rather than to the table (Tears of the Kingdom main+0x393bb0): cmp w0,#5; b.hi; ...; adr x18,#L; ldrsw x1,[x17,x0,lsl #2];
    add x18,x18,x1; br x18 → target = L + entry, with the table base x17 from adrp + add. Tried only where jump_offsets finds nothing. Returns all targets, or None if not recognized"""
    ctx = insl[max(0, j - 16):j]
    add = next((p for p in reversed(ctx) if p.mnemonic == 'add' and re.fullmatch(r'x18, x\d+, x\d+', p.op_str)), None)
    if not add: return None
    ka = ctx.index(add); ops = add.op_str.split(', ')[1:]
    for e, a in (ops, ops[::-1]):   # e = the loaded entry, a = the adr base
        ld = next((p for p in reversed(ctx[:ka]) if p.mnemonic == 'ldrsw' and re.fullmatch(rf'{e}, \[x\d+, x\d+, lsl #2\]', p.op_str)), None)
        wa = next((p for p in reversed(ctx[:ka]) if any(p.reg_name(r) == a for r in p.regs_access()[1])), None)   # the nearest writer of a
        if not ld or not wa or wa.mnemonic != 'adr': continue
        tb_reg, ix = re.fullmatch(rf'{e}, \[(x\d+), x(\d+), lsl #2\]', ld.op_str).groups()
        idx, cmp = {'w' + ix}, None   # the index and the registers copied into it (main+0x596d30: cmp w15,#8; b.hi; mov w16,w15; ...; ldrsw x0,[x17,x16,lsl #2])
        for p in reversed(ctx[:ctx.index(ld)]):   # walk back from the load to the bounds check
            m = re.fullmatch(r'(w\d+), (w\d+)', p.op_str) if p.mnemonic == 'mov' else None
            if m and m.group(1) in idx: idx.add(m.group(2)); continue
            m = re.fullmatch(r'(w\d+), #(0x[0-9a-f]+|\d+)', p.op_str) if p.mnemonic == 'cmp' else None
            if m and m.group(1) in idx: cmp = p; break
            if any('w' + p.reg_name(r)[1:] in idx for r in p.regs_access()[1]): return None   # the index changes after the check
        if cmp is None: return None
        n, at = int(cmp.op_str.split('#')[1], 0) + 1, wa.operands[1].imm
        def targets(tb): return [at + struct.unpack_from('<i', IMG, tb + 4 * i)[0] for i in range(n)] if 0 <= tb and tb + 4 * n <= len(IMG) else None
        tb = table_base(insl, insl.index(ld), tb_reg)
        if tb is not None: return targets(tb)
        # The base register was loaded further away (main+0x5f2a9c: hoisted out of the dispatch block): take every adrp + add pair in the function that builds it,
        # and accept the table only if exactly one candidate makes every target an instruction of this function
        fa, fb = insl[0].address, insl[-1].address + 4
        cands = set()
        for k, p in enumerate(insl):
            if p.mnemonic != 'adrp' or not p.op_str.startswith(tb_reg + ','): continue
            q = next((x for x in insl[k + 1:k + 9] if any(x.reg_name(r) == tb_reg for r in x.regs_access()[1])), None)
            m = re.fullmatch(rf'{tb_reg}, {tb_reg}, #(0x[0-9a-f]+|\d+)', q.op_str) if q is not None and q.mnemonic == 'add' else None
            if m: cands.add(p.operands[1].imm + int(m.group(1), 0))
        ok = [tb for tb in sorted(cands) if (t := targets(tb)) and all(fa <= x < fb and x % 4 == 0 for x in t)]
        return targets(ok[0]) if len(ok) == 1 else None
    return None
def tail_call(insl, j):
    """The br x18 is an indirect tail call, not a jump table: the last write of x18 before it is a plain pointer load and the br ends the function. Ace Attorney Investigations Collection
    (Unity 2022.3 IL2CPP) main+0x1d271bc: ldr x18,[x0,#0x18]; ...; ldr x16,[sp]; ...; br x18, a thunk that moves stack arguments and jumps to the method pointer at +0x18"""
    if j + 1 != len(insl): return False
    for p in reversed(insl[:j]):
        if 'x18' not in [p.reg_name(r) for r in p.regs_access()[1]]: continue
        return p.mnemonic == 'ldr' and bool(re.fullmatch(r'x18, \[(x\d+|sp)(, #(0x[0-9a-f]+|\d+))?\]', p.op_str))
    return False
def jump_bytes_far(insl, j):
    """The byte / halfword table form with its add further back (Octopath Traveler 0 main+0x37f9bc8: adr x18,#L; ldrb w0,[x17,x15]; add x18,x18,x0,lsl #2, then 17 register moves before br x18).
    Up to 32 instructions back, and x18 must not change between the add and the br. Tried only where the 16-instruction search and the offset forms find nothing. Returns (base, width) or None"""
    ctx = insl[max(0, j - 32):j]
    for k in range(len(ctx) - 1, -1, -1):
        p = ctx[k]
        if p.mnemonic == 'add' and p.op_str.startswith('x18, x18,') and 'lsl #2' in p.op_str: break
        if any(p.reg_name(r) == 'x18' for r in p.regs_access()[1]): return None
    else: return None
    rn = p.reg_name(p.operands[2].reg); idx = {'lr': 30, 'fp': 29}.get(rn, num(rn))
    base = next((q.operands[1].imm for q in reversed(ctx[:k]) if q.mnemonic == 'adr' and q.op_str.startswith('x18,')), None)
    ld = next((q for q in reversed(ctx[:k]) if q.mnemonic in ('ldrb', 'ldrsb', 'ldrh', 'ldrsh') and num(q.reg_name(q.operands[0].reg)) == idx), None)
    if base is None or ld is None: return None
    return base, 256 if ld.mnemonic in ('ldrb', 'ldrsb') else 65536
def disasm_fn(fa, fb):
    """A function's instructions. Capstone stops at the first word it cannot decode, so go on after it: Monster Hunter Rise main+0x6b34540 is a trap word (0xe7ffdefe)
    in the middle of a function, and the br x18 jump table after it (main+0x6b346d0) was never seen"""
    out, a = [], fa
    while a < fb:
        l = list(md.disasm(bytes(IMG[a:fb]), a))
        out += l; a = (l[-1].address + 4 if l else a) + 4
    return out
funcs = sorted({func_of(a) for a, (k, _) in kinds.items() if k == 'x18'})
for fa, fb in funcs:
    insl = disasm_fn(fa, fb)
    ws = find_windows(insl)
    for wseg in ws:
        windows.append(wseg); done |= {x.address for x in wseg}
    for j, ins in enumerate(insl):
        if ins.mnemonic == 'br' and ins.op_str == 'x18':
            base = width = None
            # 16 instructions back, as for the offset-table form: Hades main+0x1135d0 has six vector moves between the add and the br, which put its adr x18 nine back
            ctx = insl[max(0, j - 16):j]
            for p in reversed(ctx):
                if p.mnemonic == 'adr' and p.op_str.startswith('x18,'): base = p.operands[1].imm; break
            for p in reversed(ctx):
                if p.mnemonic == 'add' and p.op_str.startswith('x18, x18,') and 'lsl #2' in p.op_str:
                    # capstone names x30 'lr' (and x29 'fp'): Age of Calamity main+0x1382160 indexes with add x18,x18,x30,lsl #2 after ldrb w30,[x14,x12]
                    rn = p.reg_name(p.operands[2].reg); idx = {'lr': 30, 'fp': 29}.get(rn, num(rn))
                    for q in reversed(ctx):
                        if q.mnemonic in ('ldrb', 'ldrsb') and num(q.reg_name(q.operands[0].reg)) == idx: width = 256
                        if q.mnemonic in ('ldrh', 'ldrsh') and num(q.reg_name(q.operands[0].reg)) == idx: width = 65536
                        if width: break
                    break
            if not (base and width):
                tgt = jump_offsets(insl, j) or jump_adr_offsets(insl, j)
                if not tgt and tail_call(insl, j): tailcalls.add(ins.address); continue
                if not tgt and (far := jump_bytes_far(insl, j)): jumps[ins.address] = far; continue
                assert tgt, f'jump table {ins.address:x}'
                tabjumps[ins.address] = tgt; continue
            jumps[ins.address] = (base, width)
    # No jump may land in the middle of a window, except a retry block's branch onto the window's store-exclusive (retry_block), which gets a copy of its own
    inwin = {x.address for wseg in ws for x in wseg}; heads = {wseg[0].address for wseg in ws}
    rmid = set()
    for k, x in enumerate(insl):
        if x.mnemonic in ('b', 'bl', 'cbz', 'cbnz', 'tbz', 'tbnz') or x.mnemonic.startswith('b.'):
            t = x.operands[-1].imm
            if t in inwin and t not in heads:
                wseg = next(w for w in ws if any(y.address == t for y in w))
                rb = retry_block(insl, k, wseg) if x.mnemonic not in ('b', 'bl') else None
                assert rb, f'branch into window {x.address:x}'
                assert not any(y.address in done for y in rb[0]), f'retry block overlaps a window {rb[0][0].address:x}'
                retries.append([(rb[0], x.address + 4), (rb[1], wseg[-1].address + 4)])
                done |= {y.address for y in rb[0]}; rmid |= {y.address for y in rb[0][1:]}
    for x in insl:
        if x.mnemonic in ('b', 'bl', 'cbz', 'cbnz', 'tbz', 'tbnz') or x.mnemonic.startswith('b.'):
            assert x.operands[-1].imm not in rmid, f'branch into retry block {x.address:x}'
    for a_, tgt in tabjumps.items():
        if fa <= a_ < fb: assert not any(t in inwin and t not in heads for t in tgt), f'jump table target into window {a_:x}'

def put_branch(at, to): struct.pack_into('<I', IMG, at, B(at, to))
for wseg in windows:
    st, lo, hi = site_window(wseg); stat('window'); put_branch(lo, st)
for parts in retries:
    st = site_retry_window(parts); stat('retry_window'); put_branch(parts[0][0][0].address, st)
for a in sorted(kinds):
    if a in done: continue
    k, arg = kinds[a]
    ins = dis(struct.unpack_from('<I', IMG, a)[0], a)
    if k == 'x18':
        m = ins.mnemonic
        if m == 'br' and a in tailcalls: st = site_br_call(ins); stat('br_call')
        elif m == 'br': st = site_br_tab(ins, tabjumps[a]) if a in tabjumps else site_br(ins, *jumps[a]); stat('br')
        elif m in ('cbz', 'cbnz', 'tbz', 'tbnz'): st = site_cond(ins); stat('cond')
        elif m in ('adr', 'adrp'): st = site_pcrel(ins); stat('pcrel')
        elif m == 'blr': st = site_blr(ins); stat('blr')
        elif re.match(r'(sp|wsp),', ins.op_str): st = site_sp(ins); stat('sp')
        elif m in ('ret', 'b', 'bl') or (m == 'ldr' and '[' not in ins.op_str): raise RuntimeError(f'{a:x} {m} {ins.op_str}')
        else: st = site_plain(ins); stat('plain')
    elif k == 'tpidr_r': st = site_sysreg_read(ins, 'KTLS'); stat(k)
    elif k == 'tpidrro_r': st = site_sysreg_read(ins, 'KTLR'); stat(k)
    elif k == 'tpidr_w': st = site_tpidr_write(ins); stat(k)
    elif k == 'svc': st = site_gate(ins, 'svc', arg); stat(k)
    elif k in ('cntpct', 'cntvct'): st = site_gate(ins, k, arg); stat(k)
    elif k == 'ctr':   # replaced in place by a constant: DminLine = 4 (64-byte lines); movz xN, #4, lsl #16
        assert arg != 18, f'{a:x} mrs x18, ctr_el0'
        struct.pack_into('<I', IMG, a, 0xD2A00080 | arg); stat(k); continue
    put_branch(a, st)

obs = list(OBS.get(BUILD_ID, []))
for off, oid, ow, why in obs:
    w = struct.unpack_from('<I', IMG, off)[0]
    assert f'{w:08x}' == ow, f'observation gate original instruction mismatch {off:#x}: {w:08x}'
    # Function entries, or the instruction right after a bl, only: dm_gate writes back only x0–x8 / x30, and host C code may modify x9–x17; at entry these carry no values under AAPCS64 (arguments are only in x0–x7 / x8),
    # and right after a call returns the callee was free to clobber them anyway (x16 / x17 are the veneer registers)
    after_bl = off >= 4 and struct.unpack_from('<I', IMG, off - 4)[0] >> 26 == 0x25
    assert off in set(starts) or after_bl, f'observation gate neither at a function entry nor after a bl {off:#x}'
    assert off < TEXT_END and off not in kinds and not any(lo <= off < hi for wseg in windows for lo, hi in [(wseg[0].address, wseg[-1].address + 4)]), f'observation gate conflicts with a rewrite site {off:#x}'
    put_branch(off, site_obs(off, oid, w)); stat('obs')

# ---- Frame step in whole vsyncs (The Legend of Zelda: Tears of the Kingdom 1.4.3, Breath of the Wild 1.9.0 and Hyrule Warriors: Age of Calamity 1.3.0 main, host only) ----
# The games step their game time by a whole number of vsyncs (1/60 s) per frame that their own interval logic picks. With the stubs the host picks it (hle_nvn.c fstep_tick,
# nvn_fstep.h): the step is the number of vsyncs the host keeps the frame on screen (1 = 60 fps, 2 = 30 when 60 does not hold), plus one while the game is behind real time after
# a late frame, so motion is even and game time = real time. The steps stay values the games' own logic uses (1 to 3). Age of Calamity's updates are not held by the presents:
# its stubs run them at the cap, and the host only paces its presents (below).
# State page = the page after the key page (zero in the file, read-write in both loaders): +0 float target fps written by the loader (fps_target, DM_FPS_TARGET; 0 = every stub
# runs the original instructions), +4 TOTK movie flag, +8 double lead (TOTK, below), +0x10 float render scale (TOTK, below), +0x18 double game seconds (TOTK, below),
# +0x20 u32 step in vsyncs (host; 0 = not decided yet), +0x24 u32 a step the game fixes itself (BotW's VFR override; 0 = none), +0x28 u32 AoC's vsyncs per update, marked by
# its first stub (0 = off), +0x30 u64 vsyncs stepped (the stubs; logged by the host to check the game's speed). Stub bodies assembled with clang
FRAME_STEP = {'277178b7dba1b6d4949a84778d4abc58', 'cd57b23fa4bbad65803d9788c01821ee', 'c3cf52bf2b05d7310884971b50bcccb8'}
FS_STATE_OFF = 0
if BUILD_ID in FRAME_STEP and NAME == 'main':
    FS_STATE_OFF = KEY_PAGE_OFF + 0x4000
    assert not FAR and FS_STATE_OFF % 0x1000 == 0 and FS_STATE_OFF + 0x40 <= PATCH_OFF and not any(IMG[FS_STATE_OFF:]), 'frame step state page'
    def fs_site(off, orig):
        ob = bytes.fromhex(orig)
        assert IMG[off:off + len(ob)] == ob, f'frame step original bytes mismatch {off:#x}: {bytes(IMG[off:off + len(ob)]).hex()}'
        for o in range(off, off + len(ob), 4):
            assert o not in kinds and not any(seg[0].address <= o < seg[-1].address + 4 for seg in windows), f'frame step site is a rewrite site {o:#x}'
    def fs_put(off, words, why):
        old = bytes(IMG[off:off + 4 * len(words)])
        for i, w in enumerate(words): struct.pack_into('<I', IMG, off + 4 * i, w)
        cuts.append((off, old.hex(), bytes(IMG[off:off + 4 * len(words)]).hex(), why)); stat('frame_step')
# Tears of the Kingdom picks a present interval each frame (main+0x2db174: 2 = 30 fps, 3 under load) and steps its game time by 60 / fps (int fps at timing +0x50, read at main+0x2daa54
# and main+0x3e562c). The stub replaces that logic: int fps = 60 / step, and the float fps (timing +0x24, unused, per masagrator's FPSLocker config for this build, which found the
# sites) the same, which the consumers read. Until the host has decided a step (the first frames) the step is the measured frame time (timing frame +0xd8, 19.2 MHz
# ticks), clamped to [1 / cap, 1 / 15 s]; game time that ran ahead after a short frame (the "lead", at most 0.25 s; totk-mobile) is paid back by later frames. Prerendered movies set a 30 cap (flag set and cleared around main+0x2b36100 /
# main+0x2b33918), the D-pad menu fade starts at full rate (FPSLocker's fix at main+0x1fbc80) and the swapchain argument at main+0xbe14a8 becomes 1 as in FPSLocker
if FS_STATE_OFF and BUILD_ID == '277178b7dba1b6d4949a84778d4abc58':
    # frame step (replaces ldrb w9,[x0,#0x58], the first instruction after the prologue)
    fs_site(0x2db18c, '09604139')
    start = here(); emit(ADRP(16, here(), FS_STATE_OFF))
    for w in (0xbd400200,   # ldr s0,[x16]           target fps
              0x1e202008,   # fcmp s0,#0.0
              0x54000640,   # b.eq off (+50)        target 0: original path
              0xb9402202,   # ldr w2,[x16,#0x20]     step in vsyncs
              0x340001a2,   # cbz w2,elapsed (+13)   not decided yet: by the measured frame time
              0x1e230041,   # ucvtf s1,w2
              0x1e27d003,   # fmov s3,#30.0
              0x1e211872,   # fdiv s18,s3,s1
              0x1e322a52,   # fadd s18,s18,s18       fps = 60 / step
              0xbd002412,   # str s18,[x0,#0x24]     float fps
              0x52800785,   # mov w5,#60
              0x1ac208a5,   # udiv w5,w5,w2
              0xb9005005,   # str w5,[x0,#0x50]      integer fps
              0xf9401a04,   # ldr x4,[x16,#0x30]
              0x8b224084,   # add x4,x4,w2,uxtw
              0xf9001a04):  # str x4,[x16,#0x30]     vsyncs stepped
        emit(w)
    emit(B(here(), 0x2db284))                                       # the original epilogue
    for w in (0xf9406c22,   # elapsed: ldr x2,[x1,#0xd8]  last frame time in 19.2 MHz ticks
              0x9e630041,   # ucvtf d1,x2
              0x529f0003,   # mov w3,#0xf800
              0x72a02483,   # movk w3,#0x124,lsl #16 (19,200,000)
              0x1e630062,   # ucvtf d2,w3
              0x1e621821,   # fdiv d1,d1,d2          elapsed seconds
              0xb9400604,   # ldr w4,[x16,#4]        movie flag
              0x1e27d003,   # fmov s3,#30.0
              0x7100009f,   # cmp w4,#0
              0x1e201c60,   # fcsel s0,s3,s0,ne      cap = movie ? 30 : target
              0x1e22c000,   # fcvt d0,s0
              0x1e6e1003,   # fmov d3,#1.0
              0x1e601864,   # fdiv d4,d3,d0          shortest step 1 / cap
              0x1e65d005,   # fmov d5,#15.0
              0x1e651865,   # fdiv d5,d3,d5          longest step 1 / 15
              0xfd400606,   # ldr d6,[x16,#8]        lead
              0x1e663827,   # fsub d7,d1,d6
              0x1e6448e7,   # fmax d7,d7,d4
              0x1e6558e7,   # fmin d7,d7,d5          step = clamp(elapsed - lead)
              0x1e6728c6,   # fadd d6,d6,d7
              0x1e6138c6,   # fsub d6,d6,d1          lead += step - elapsed
              0x2f00e410,   # movi d16,#0
              0x1e7048c6,   # fmax d6,d6,d16
              0x1e6a1011,   # fmov d17,#0.25
              0x1e7158c6,   # fmin d6,d6,d17         lead in [0, 0.25]
              0xfd000606,   # str d6,[x16,#8]
              0x1e671872,   # fdiv d18,d3,d7         fps = 1 / step
              0x1e624252,   # fcvt s18,d18
              0xbd002412,   # str s18,[x0,#0x24]     float fps
              0x1e380245,   # fcvtzs w5,s18
              0xb9005005,   # str w5,[x0,#0x50]      integer fps
              0xfd400e13,   # ldr d19,[x16,#0x18]
              0x1e672a73,   # fadd d19,d19,d7
              0xfd000e13):  # str d19,[x16,#0x18]    game seconds stepped
        emit(w)
    emit(B(here(), 0x2db284))                                       # the original epilogue
    emit(0x39416009); emit(B(here(), 0x2db190))                     # off: ldrb w9,[x0,#0x58]; back
    fs_put(0x2db18c, [B(0x2db18c, start)], 'frame step from the host in whole vsyncs, by elapsed time until it has decided one (state page target fps; 0 = original interval logic)')
    # the two readers of the integer fps: float fps when on; the scvtf a few instructions later moves into the stub (s0 is not touched in between)
    for site, cvt, r in ((0x2daa54, 0x2daa6c, 19), (0x3e562c, 0x3e5638, 22)):
        fs_site(site, struct.pack('<I', 0xbd425000 | r << 5).hex()); fs_site(cvt, '00d8215e')
        start = here(); emit(STP_PRE(16, 17, 31, -16)); emit(ADRP(16, here(), FS_STATE_OFF))
        for w in (0xb9400211,                # ldr w17,[x16]
                  0x34000071,                # cbz w17,off (+12)
                  0xbd422400 | r << 5,       # ldr s0,[xR,#0x224]  float fps
                  0x14000003,                # b done (+12)
                  0xbd425000 | r << 5,       # off: ldr s0,[xR,#0x250]  integer fps
                  0x5e21d800,                # scvtf s0,s0
                  0xa8c147f0):               # done: ldp x16,x17,[sp],#16
            emit(w)
        emit(B(here(), site + 4))
        fs_put(site, [B(site, start)], 'game step reads the float fps (original integer fps and scvtf when off)')
        fs_put(cvt, [NOP], 'scvtf moved into the stub at the load')
    # D-pad menu fade (w8 is overwritten right after the site)
    fs_site(0x1fbc80, '0820201e0a04081f')
    start = here(); emit(ADRP(8, here(), FS_STATE_OFF))
    for w in (0xb9400108, 0x340001a8,       # ldr w8,[x8]; cbz w8,off (+52)
              0x1e202028, 0x54000101,       # fcmp s1,#0.0; b.ne go
              0x785fa308, 0x7100151f, 0x540000a1,   # ldurh w8,[x24,#-6]; cmp w8,#5; b.ne go
              0x785f8308, 0x7100151f, 0x54000041,   # ldurh w8,[x24,#-8]; cmp w8,#5; b.ne go
              0x1e2e1008,                   # fmov s8,#1.0
              0x1f08040a, 0x1e202008, 0x14000003,   # go: fmadd s10,s0,s8,s1; fcmp s0,#0.0; b end
              0x1e202008, 0x1f08040a):      # off: the original fcmp s0,#0.0; fmadd s10,s0,s8,s1
        emit(w)
    emit(B(here(), 0x1fbc88))
    fs_put(0x1fbc80, [B(0x1fbc80, start), NOP], 'D-pad menu fade starts at full rate under fractional steps (FPSLocker)')
    # swapchain argument (x16 is dead before the bl that follows)
    fs_site(0xbe14a8, '61a24039')
    start = here(); emit(ADRP(16, here(), FS_STATE_OFF))
    for w in (0xb9400210, 0x34000070, 0x52800021, 0x14000002, 0x3940a261):   # ldr w16,[x16]; cbz w16,off; mov w1,#1; b end; off: ldrb w1,[x19,#0x28]
        emit(w)
    emit(B(here(), 0xbe14ac))
    fs_put(0xbe14a8, [B(0xbe14a8, start)], 'swapchain argument 1 when on (FPSLocker)')
    # prerendered movie start and end set and clear the flag (x16 / x17 are free at a call)
    fs_site(0x2b36100, 'b6f37097'); fs_site(0x2b33918, 'de170214')
    start = here(); emit(ADRP(16, here(), FS_STATE_OFF)); emit(0x52800031); emit(0xb9000611); emit(B(here(), 0x772fd8))   # mov w17,#1; str w17,[x16,#4]; tail call
    fs_put(0x2b36100, [B(0x2b36100, start) | 0x80000000], 'movie starts: 30 fps cap')
    start = here(); emit(ADRP(16, here(), FS_STATE_OFF)); emit(0xb900061f); emit(B(here(), 0x2bb9890))                     # str wzr,[x16,#4]; tail call
    fs_put(0x2b33918, [B(0x2b33918, start)], 'movie ends')
    # Render scale (state +0x10, float written by the loader: DM_RENDER_SCALE, 1.0 by default). main+0xd5c24 sizes each view: screen size x the view's scale (5/6 for the scene: 1600x896
    # docked) x the dynamic-resolution multiplier, clamped to 8..16384 and floored to the view's alignment. The stub multiplies both extents by the factor (s6, w8 and the flags are dead
    # at main+0xd5cc0: s6 is set to 8.0 right after); any factor but 1.0 also replaces the dynamic multiplier (main+0xd5d80) with 1, so the size is fixed. 1.0 = bit-exact original
    fs_site(0xd5cc0, '08d0a8524008251e6108241e0401271e'); fs_site(0xd5d80, '062940bd')
    start = here(); emit(ADRP(8, here(), FS_STATE_OFF))
    for w in (0xbd401106,   # ldr s6,[x8,#0x10]   render scale
              0x1e250840,   # fmul s0,s2,s5       (original)
              0x1e240861,   # fmul s1,s3,s4       (original)
              0x1e2020c8,   # fcmp s6,#0.0
              0x5400006d,   # b.le skip (+12)     not set
              0x1e260800,   # fmul s0,s0,s6
              0x1e260821,   # fmul s1,s1,s6
              0x52a8d008,   # skip: mov w8,#0x46800000 (original)
              0x1e270104):  # fmov s4,w8          (original)
        emit(w)
    emit(B(here(), 0xd5cd0))
    fs_put(0xd5cc0, [B(0xd5cc0, start)], 'view render size x the host render scale (1.0 = original)')
    start = here(); emit(0xbd402906); emit(ADRP(8, here(), FS_STATE_OFF))   # ldr s6,[x8,#0x28] (original: the dynamic multiplier); x8 is dead after it
    for w in (0xbd401107,   # ldr s7,[x8,#0x10]
              0x1e2e1010,   # fmov s16,#1.0
              0x1e3020e0,   # fcmp s7,s16
              0x54000080,   # b.eq done (+16)     scale 1: the game's dynamic resolution
              0x1e2020e8,   # fcmp s7,#0.0
              0x5400004d,   # b.le done (+8)      not set
              0x1e204206):  # fmov s6,s16         a fixed scale: no dynamic multiplier
        emit(w)
    emit(B(here(), 0xd5d84))
    fs_put(0xd5d80, [B(0xd5d80, start)], 'dynamic resolution only at render scale 1.0')
# Breath of the Wild: the framework's interval controller (the 60 fps cuts above) hands its interval to setWaitVsyncInterval (main+0x11269b8), which the main loop calls once a frame
# (main+0x11267c0); the framework keeps it at fw+0x244 (getter vtable +0x138, read by both callers of VFR::updateInterval and directly in 43 places) and passes it on to
# nvnWindowSetPresentInterval. The stub at the setter's entry replaces it with the host's step, read once a frame: ksys::VFR::updateInterval (main+0x151d3d0, x0 = the VFR at
# [main+0x1e93890]; called from GameScene::calc and the per-frame delegate main+0x1280f80) takes the framework's interval in the next frame (ratio = step / 2, base interval 2, and the
# int interval that 16 pieces of logic read), so the time step and everything else that reads the interval agree. The step is not written into the VFR call itself: the game presents
# on its own thread, so the host's step can change between the two VFR calls of a frame. The VFR's own override (+0x29 flag, +0x2c interval: 2 at main+0xc3b588 and main+0xc5ebf8,
# 1 at main+0xc609d8, set and cleared by game scenes) wins in the VFR:
# a stub there publishes it at state +0x24 so the host holds frames that long, and the setter stub leaves the framework's interval to the game while it is set. x16 / x17 are free
# at both entries
if FS_STATE_OFF and BUILD_ID == 'cd57b23fa4bbad65803d9788c01821ee':
    fs_site(0x11269b8, 'fd7bbea9'); fs_site(0x151d3d0, 'fd7bbea9')
    start = here(); emit(ADRP(16, here(), FS_STATE_OFF))
    for w in (0xb9400211,   # ldr w17,[x16]          target fps (0 = off)
              0x34000191):  # cbz w17,orig (+12)
        emit(w)
    emit(ADRP(17, here(), 0x1e93890)); emit(LDRX(17, 17, 0x890 // 8))   # the VFR
    for w in (0xb4000131,   # cbz x17,orig (+9)
              0x3940a631,   # ldrb w17,[x17,#0x29]   the VFR's override
              0x350000f1,   # cbnz w17,orig (+7)     the framework keeps the game's interval
              0xb9402211,   # ldr w17,[x16,#0x20]    step in vsyncs
              0x340000b1,   # cbz w17,orig (+5)      not decided yet
              0x2a1103e1,   # mov w1,w17
              0xf9401a11,   # ldr x17,[x16,#0x30]
              0x8b214231,   # add x17,x17,w1,uxtw
              0xf9001a11,   # str x17,[x16,#0x30]    vsyncs stepped
              0xa9be7bfd):  # orig: stp x29,x30,[sp,#-0x20]!
        emit(w)
    emit(B(here(), 0x11269bc))
    fs_put(0x11269b8, [B(0x11269b8, start)], 'setWaitVsyncInterval: the host\'s step unless the VFR override is set (state page target fps; 0 = the game\'s interval)')
    start = here(); emit(ADRP(16, here(), FS_STATE_OFF))
    for w in (0xb9400211,   # ldr w17,[x16]          target fps (0 = off)
              0x340000b1,   # cbz w17,orig (+5)
              0x3940a411,   # ldrb w17,[x0,#0x29]    the VFR's override
              0x34000051,   # cbz w17,pub (+2)       none: 0
              0xb9402c11,   # ldr w17,[x0,#0x2c]
              0xb9002611,   # pub: str w17,[x16,#0x24]  the game's own step: the host holds frames that long
              0xa9be7bfd):  # orig: stp x29,x30,[sp,#-0x20]!
        emit(w)
    emit(B(here(), 0x151d3d4))
    fs_put(0x151d3d0, [B(0x151d3d0, start)], 'VFR::updateInterval: its own override published for the host (state page target fps; 0 = original)')
    # Render scale (state +0x10, float written by the loader: DM_RENDER_SCALE, 1.0 by default; independent of the frame step). The dynamic-resolution method (main+0x12666e4) keeps a
    # scale in 0.8–1.0 rounded to 0.05 steps (+0x1218, main+0x1266818), or the game's forced 0.75 / 0.5 (+0x284 & 0x1800), in s8; from main+0x1266880 it applies s8: each view's
    # scale (+0x28a0 / +0x28a4 = s8 × base width (+0x1214: 1600 docked, 1280 handheld) / output width), from which the scene buffers are sized each frame (main+0x106340c), the
    # shader ratio uking_dynamic_resolution_ratio and the other readers (main+0xc3c3f4, an LOD check at main+0x14126b4). Setting s8 there keeps them all consistent (a multiply in the
    # size function, TOTK's way, would leave the ratio and those readers at the old scale). The apply block runs only when the dynamic path has just recomputed the scale (+0x280 bit 4,
    # set at main+0x1266830) or in a forced mode, else main+0x126686c skips it; with a factor it is taken every frame, as in the dynamic mode, so the factor holds with dynamic
    # resolution off too. Factors above 1.0 are refused by the loader: the per-frame texture pool's size is unknown. x8, s0, s1 and the flags are dead at both sites
    fs_site(0x1266880, '88ae40f9'); fs_site(0x126686c, struct.pack('<I', B(0x126686c, 0x1266950)).hex())
    apply = here(); emit(ADRP(8, here(), FS_STATE_OFF))
    for w in (0xbd401100,   # ldr s0,[x8,#0x10]      render scale
              0x1e202008,   # fcmp s0,#0.0
              0x540000ad,   # b.le orig (+5)         not set
              0x1e2e1001,   # fmov s1,#1.0
              0x1e212000,   # fcmp s0,s1
              0x54000040,   # b.eq orig (+2)         1.0: the game's own scale
              0x1e204008,   # fmov s8,s0             the host's scale
              0xf940ae88):  # orig: ldr x8,[x20,#0x158]
        emit(w)
    emit(B(here(), 0x1266884))
    fs_put(0x1266880, [B(0x1266880, apply)], '3D view scale = the host render scale (1.0 = the game\'s dynamic resolution)')
    start = here(); emit(ADRP(8, here(), FS_STATE_OFF))
    for w in (0xb9401108,   # ldr w8,[x8,#0x10]      render scale (float bits)
              0x34000088,   # cbz w8,skip (+4)       not set
              0x52091908,   # eor w8,w8,#0x3f800000
              0x34000048):  # cbz w8,skip (+2)       1.0
        emit(w)
    emit(B(here(), 0x1266880)); emit(B(here(), 0x1266950))   # apply the host's scale; skip: the original branch
    fs_put(0x126686c, [B(0x126686c, start)], 'scale apply block taken every frame when the host render scale is not 1.0')
# Hyrule Warriors: Age of Calamity steps its game a fixed amount per update, from two 30 fps values. A KIDS task (main+0x166d980, on a KIDSTaskScheduler thread, once per update)
# waits until 1 / fps has passed since the last update (fps at time +0x30: 30 from a frame-rate object, main+0x166daa4; csinc at main+0x166db80) and then steps the game clock
# (system +0x3348, the step at +0x3350) by that object's step (x23 +0x34: 1/30 s times the game's timescale, a second time at +0x44, fps 30 at +0x48), not by the time that
# passed (the measured path, main+0x166dca8, runs only without the object). The battle itself steps 1 / the game's frame rate per update: a block at main+0x269e150 {fps,
# interval, fps, float fps} = {30, 2, 30, 30.0}, read by the scene update's caller (main+0x8c3610: step = 1.0 / fps) and its jobs (32 reads; the game's own writers at
# main+0x8a35e0 / main+0xfc1618, a run-time interval request at +0x1d58, never ran in a probe). The event scripts step by the KTGL device's frame rate (device +0x32d0, from the
# interval in its config: the third stub). The updates are not held by the presents (a task kept 60 a second while the host held frames 3 vsyncs), so they run at the cap and
# the host's frame step paces only the presents: at main+0x166dab4 (where both fps paths join, before the update's tasks and the wait) the task's fps and the frame-rate block
# become the cap (60, or 30 at a 30 cap), the update's vsyncs (60 / cap) are marked (+0x28) and the device frame rate becomes 59.94 / those vsyncs; at main+0x166dc60 the
# object's steps are scaled by its fps × vsyncs / 60 and the vsyncs are counted. Every step is then per update as on the Switch, so an update rate below the cap slows them all
# together. With only the task's wait at 1/60 s the game clock ran at twice real time; with the clock fixed and the block left at 30, battles still ran at twice (Link covered
# twice the ground in a 3 s stick hold; enemy waves came early). Off (target 0), the device frame rate follows the game's fps (29.97 at 30, as with interval 2) and the steps and
# the block stay the game's. x16, x17, s16–s18 and the flags are dead at both sites; the function uses no x16 / x17
if FS_STATE_OFF and BUILD_ID == 'c3cf52bf2b05d7310884971b50bcccb8':
    fs_site(0x166dab4, '68734339'); fs_site(0x166dc60, 'e83640b9'); fs_site(0x8d94b0, '4900c0f2')
    # nnMain builds KTGL's device config on its stack and inits the device once (main+0x8d94c4 → main+0x17c34f0): {1920, 1080, 3, 9, 5, interval 2, 9, …}. The device keeps the
    # interval (main+0x17c4ba8 → device +0x2aa4, passed to every present at main+0x17ced78, which sets it on the window when it changes) and its frame rate, 59.94 / interval
    # (main+0x17c37c8 → device +0x32d0). Interval 1 above a 30 fps cap (the engine's own 60 fps mode), else the game's 2. x16, x17 and the flags are dead up to the init call
    start = here(); emit(ADRP(16, here(), FS_STATE_OFF))
    for w in (0xb9400210,   # ldr w16,[x16]          target fps (float bits)
              0x52a83e11,   # mov w17,#0x41f00000    30.0
              0x6b11021f,   # cmp w16,w17
              0x5400006d,   # b.le two (+3)
              0xf2c00029):  # movk x9,#0x1,lsl #32   interval 1
        emit(w)
    emit(B(here(), 0x8d94b4)); emit(0xf2c00049); emit(B(here(), 0x8d94b4))   # two: movk x9,#0x2,lsl #32 (the original)
    fs_put(0x8d94b0, [B(0x8d94b0, start)], 'KTGL device config present interval: 1 above a 30 fps cap, else the game\'s 2 (state page target fps)')
    start = here(); emit(ADRP(16, here(), FS_STATE_OFF))
    for w in (0xbd400210,   # ldr s16,[x16]          target fps (0 = off)
              0x1e202208,   # fcmp s16,#0.0
              0x540001ad,   # b.le off (+13)
              0x1e380208,   # fcvtzs w8,s16          the cap
              0xb9003268,   # str w8,[x19,#0x30]     the task's fps
              0x52800791,   # mov w17,#60
              0x1ac80a31,   # udiv w17,w17,w8        vsyncs per update
              0xb9002a11):  # str w17,[x16,#0x28]    this update's vsyncs (on)
        emit(w)
    emit(ADRP(16, here(), 0x269e150))
    for w in (0xb9015208,   # str w8,[x16,#0x150]    the game's frame-rate block: fps
              0xb9015611,   # str w17,[x16,#0x154]   interval
              0xb9015a08,   # str w8,[x16,#0x158]    fps
              0x1e220111,   # scvtf s17,w8
              0xbd015e11,   # str s17,[x16,#0x15c]   float fps (the battle's step is 1 / it)
              0x14000007,   # b dev (+7)
              0xb9002a1f,   # off: str wzr,[x16,#0x28]
              0xb9403268,   # ldr w8,[x19,#0x30]     the game's fps
              0x34000188,   # cbz w8,orig (+12)
              0x52800791,   # mov w17,#60
              0x1ac80a31,   # udiv w17,w17,w8        vsyncs per update at that fps
              0x34000131):  # cbz w17,orig (+9)
        emit(w)
    emit(ADRP(16, here(), 0x2bac798))                                # dev:
    for w in (0xf943ce10,   # ldr x16,[x16,#0x798]   the KTGL device
              0xb40000d0):  # cbz x16,orig (+6)
        emit(w)
    emit(ADRP(8, here(), 0x1ef5f3c))
    for w in (0xbd4f3d10,   # ldr s16,[x8,#0xf3c]    59.94
              0x1e230231,   # ucvtf s17,w17
              0x1e311a10,   # fdiv s16,s16,s17
              0xbd32d210,   # str s16,[x16,#0x32d0]  the device frame rate
              0x39437368):  # orig: ldrb w8,[x27,#0xdc]
        emit(w)
    emit(B(here(), 0x166dab8))
    fs_put(0x166dab4, [B(0x166dab4, start)], 'KIDS frame task: fps and the frame-rate block = the cap, vsyncs per update marked; device frame rate 59.94 / vsyncs (state page target fps; 0 = the game\'s 30)')
    start = here(); emit(0xbd4036f0)   # ldr s16,[x23,#0x34]    the frame-rate object's step
    emit(ADRP(16, here(), FS_STATE_OFF))
    for w in (0xb9402a11,   # ldr w17,[x16,#0x28]    vsyncs per update (0 = off)
              0x340001f1,   # cbz w17,off (+15)
              0xf9401a08,   # ldr x8,[x16,#0x30]
              0x8b314108,   # add x8,x8,w17,uxtw
              0xf9001a08,   # str x8,[x16,#0x30]     vsyncs stepped
              0xb9404ae8,   # ldr w8,[x23,#0x48]     the object's fps
              0x34000148,   # cbz w8,off (+10)
              0x1b087e31,   # mul w17,w17,w8
              0x1e230231,   # ucvtf s17,w17
              0x52800788,   # mov w8,#60
              0x1e230112,   # ucvtf s18,w8
              0x1e321a31,   # fdiv s17,s17,s18       its fps × vsyncs / 60
              0xbd4046e0,   # ldr s0,[x23,#0x44]
              0x1e310a10,   # fmul s16,s16,s17
              0x1e310800,   # fmul s0,s0,s17
              0x14000002,   # b out (+2)
              0xbd4046e0,   # off: ldr s0,[x23,#0x44]
              0x1e260208,   # out: fmov w8,s16
              0xb9001a68):  # str w8,[x19,#0x18]     the update's step
        emit(w)
    emit(B(here(), 0x166dc6c))
    fs_put(0x166dc60, [B(0x166dc60, start)], 'KIDS frame task: the frame-rate object\'s steps × its fps × vsyncs per update / 60 (state page target fps; 0 = as the game sets them)')

os.makedirs(outdir, exist_ok=True)
P = lambda ext: os.path.join(outdir, f'{NAME}.{ext}')
if FAR:   # patch area before the base: file = text + ro + data (padded to 16K) + patch area
    if BIG_TEXT and len(patch) > FRONT - 0x4000 and 'DM_PATCH_FRONT' not in os.environ:
        need = (len(patch) + 0x4000 + 0xFFFF) & ~0xFFFF
        print(f'{NAME}: patch area of {len(patch):#x} bytes does not fit in {FRONT:#x} before the base; rewriting again with {need:#x}', flush=True)
        os.execve(sys.executable, [sys.executable] + sys.argv, dict(os.environ, DM_PATCH_FRONT=hex(need)))
    assert len(patch) <= FRONT - 0x4000, f'patch area of {len(patch):#x} bytes does not fit in the {FRONT:#x} before the base'
    open(P('patched.bin'), 'wb').write(IMG + bytearray(FILE_IMAGE_LEN - len(IMG)) + patch)
else:
    open(P('patched.bin'), 'wb').write(IMG + bytearray(PATCH_OFF - len(IMG)) + patch)
import hashlib
with open(os.path.join(outdir, 'build_src.sha256'), 'w') as f:
    f.write(hashlib.sha256(open(os.path.abspath(__file__), 'rb').read()).hexdigest() + '  patch_nso.py\n')
with open(P('fixups.tsv'), 'w') as f:
    f.write(f'# PATCH_OFF\t{PATCH_OFF:#x}\n# KEY_PAGE_OFF\t{KEY_PAGE_OFF:#x}\n# KEY_PAGE_SIZE\t0x4000\n# TEXT_END\t{TEXT_END:#x}\n# RO_OFF\t{RO_OFF:#x}\n# DATA_OFF\t{DATA_OFF:#x}\n')
    if FAR: f.write(f'# IMAGE_SIZE\t{IMAGE_SIZE:#x}\n# FILE_IMAGE_LEN\t{FILE_IMAGE_LEN:#x}\n')   # patch area before the base (negative PATCH_OFF): whole image size, length of the image part of the file
    for k in KEY_INDEX: f.write(f'# KEY_{k}_IDX\t{KEY_INDEX[k]}\n')
    if FS_STATE_OFF: f.write(f'# FPS_STATE_OFF\t{FS_STATE_OFF:#x}\n')   # frame step state page (FRAME_STEP): the loader writes the target fps there
    f.write(f'# BUILD_ID\t{BUILD_ID}\n')   # the host identifies the build by it: features with hard-coded addresses only run on the build they belong to
with open(P('gates.tsv'), 'w') as f:
    for ret, k, arg, orig in gates: f.write(f'{ret:#x}\t{k}\t{arg}\t{orig:#x}\n')
with open(P('sites.tsv'), 'w') as f:
    for a in sorted(kinds):
        if a not in done: f.write(f'{a:#x}\t{kinds[a][0]}\n')
    for wseg in windows: f.write(f'{wseg[0].address:#x}\tW\t{wseg[-1].address + 4:#x}\n')
    for a, (b, c) in jumps.items(): f.write(f'{a:#x}\tJ\t{b:#x}\t{c}\n')
    for a, tgt in tabjumps.items(): f.write(f'{a:#x}\tT\t' + ' '.join(f'{t:#x}' for t in tgt) + '\n')   # offset-table jump and all its targets
with open(P('cuts.tsv'), 'w') as f:
    f.write(f'# BUILD_ID\t{BUILD_ID}\n')
    for off, ob, nb, why in cuts: f.write(f'{off:#x}\t{ob}\t{nb}\t{why}\n')   # Columns: offset, original bytes, new bytes, reason
with open(P('obs.tsv'), 'w') as f:
    f.write(f'# BUILD_ID\t{BUILD_ID}\n')
    for off, oid, ow, why in obs: f.write(f'{off:#x}\t{oid}\t{ow}\t{why}\n')
print(NAME, stats, 'cuts', len(cuts), 'obs', len(obs), 'patch', len(patch), 'PATCH_OFF', hex(PATCH_OFF), 'slot_refs', len(fix), 'gates', len(gates))
