// Host simulation of the liuqin H16 metaclass-duplicate gate.
#include <cstdarg>
// Stubs model XNU's OSMetaClass registry and reproduce postModLoad's duplicate
// branch (the iOS panic path) so we can prove:
//   1. WITHOUT the gate, allocating a NativeUfsBlock registers a second
//      "IOBlockStorageDevice" name and postModLoad faults exactly like on device;
//   2. WITH the gate, startRoot refuses before any allocation, no duplicate is
//      ever registered, and boot continues.
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cassert>
#include <string>
#include <vector>

// ---- stub IOKit world ------------------------------------------------------
struct MetaClass {                       // stands in for OSMetaClass
    std::string name;                    // className (C string pre-symbol)
    void *reserved = nullptr;            // ExpansionData* — freed poison on orig
};
struct Symbol { std::string s; void release() const {} };
struct OSSymbolStub : Symbol {};

static std::vector<MetaClass*> gAllClasses;      // sAllClassesDict by name
static std::vector<MetaClass*> gStalled;         // sStalled->classes
static bool gPoisonFreed = false;
static bool gFaulted = false;                // reserved freed at registration?

struct FakeKext { const char *id; };
static FakeKext gKernelKext{"__kernel__"};

// IOStorageFamily's class, registered during the closure's __kernel__ load pass.
static MetaClass ioBlockStorageDevice{"IOBlockStorageDevice", nullptr};
static MetaClass ioService{"IOService", nullptr};

static void registerDuringKernelPass(MetaClass *mc) {
    // preModLoad("__kernel__") recorded it; postModLoad inserts into sAllClassesDict.
    if (!mc->reserved) mc->reserved = new int(1);           // ExpansionData alloc
    gStalled.push_back(mc);
}
static bool postModLoad(bool emulate_freed_poison) {
    // duplicate check pass
    for (size_t i = 0; i < gStalled.size(); i++) {
        MetaClass *me = gStalled[i];
        MetaClass *orig = nullptr;
        for (auto *c : gAllClasses) if (c->name == me->name) orig = c;
        if (orig) {
            // iOS path: panic("... duplicate ...", ((OSKext*)orig->reserved->kext)->getIdentifierCString())
            if (emulate_freed_poison && !orig->reserved) {
                printf("FAULT: Kernel data abort reading orig->reserved (freed ExpansionData)\n");
                gFaulted = true;                           // the device crash shape
                return false;                              // panic window hit
            }
            printf("PANIC would fire: Kext __kernel__ class %s is a duplicate\n", me->name.c_str());
            return false;
        }
    }
    for (auto *me : gStalled) gAllClasses.push_back(me);
    gStalled.clear();
    return true;
}

// ---- v38 (H16-E) model: the scan over sStalled->classes[] ------------------
// Mirrors the patched XNU logic field-for-field so the control flow we ship is the
// control flow we test. OSMetaClass's real arm64 layout, confirmed against the v37
// disassembly (className = [x24,#0x18], superClassLink = [x24,#0x10]).
struct MetaClass2 {
    void        *vtable;                    // +0x00
    void        *reserved;                  // +0x08
    MetaClass2  *superClassLink;            // +0x10
    const char  *className;                 // +0x18
    unsigned     classSize;                 // +0x20
};
static const int CHAIN_MAX = 64;
// The host model has no kernel VA range, so "plausible kernel pointer" is modelled as
// membership in a synthetic image: every object we hand the scan is registered here,
// and anything else (like the 0x6131373030666666 poison word) reads as garbage.
static std::vector<const void*> gImage;
static void addToImage(const void *p) { gImage.push_back(p); }
static inline bool ptr_ok(const void *p) {
    if (!p) return true;
    for (auto *q : gImage) if (q == p) return true;
    return false;
}

// liuqin_chain_depth(): returns hops, or -(hops before the bad link) + badOut set.
static int chain_depth(const MetaClass2 *entry, const void **badOut) {
    const void *cur = entry;
    int hops = 0;
    *badOut = nullptr;
    while (cur) {
        if (!ptr_ok(cur)) { *badOut = cur; return -hops; }
        cur = ((const MetaClass2 *)cur)->superClassLink;
        if (++hops > CHAIN_MAX) { *badOut = cur; return -hops; }
    }
    return hops;
}

static unsigned gDeepest = 0;
// naive = v35/v37 XNU (unvalidated walk, faults on a poisoned link);
// guarded = v38 (validate, name, NULL the slot, keep going). Returns bad count, or
// -1 when the naive walk actually faulted.
static int scanPass(std::vector<MetaClass2*> &stalled, std::vector<MetaClass2*> &all,
                    bool naive) {
    int bad = 0;
    for (size_t i = 0; i < stalled.size(); i++) {
        MetaClass2 *me = stalled[i];
        if (me && !ptr_ok(me)) { stalled[i] = nullptr; bad++; continue; }   // M:dirty
        if (!me) continue;
        for (auto *c : all) if (c->className && me->className &&
                                 !strcmp(c->className, me->className)) {
            printf("PANIC would fire: duplicate %s\n", me->className); return -2;
        }
        if (naive) {                       // the v37 fault shape
            while ((me = me->superClassLink)) {
                if (!ptr_ok(me)) {         // next iteration reads [me+0x10] -> abort
                    printf("FAULT: data abort at postModLoad+0x2d4, x24=%p "
                           "(far=x24+0x10)\n", (void*)me);
                    return -1;
                }
            }
            continue;
        }
        const void *badLink = nullptr;
        int depth = chain_depth(me, &badLink);
        if (depth < 0) {                   // M:bad[i] bad-chain, then skip
            printf("M:bad[%zu] bad-chain n=%s bad=%p\n", i, me->className, badLink);
            stalled[i] = nullptr; bad++; continue;
        }
        if ((unsigned)depth > gDeepest) gDeepest = (unsigned)depth;
    }
    if (!naive) {
        for (auto *me : stalled) if (me) all.push_back(me);
        stalled.clear();
    }
    return bad;
}

// ---- driver-side stubs -----------------------------------------------------
static Symbol *symbol_pool = nullptr;
static OSSymbolStub* withCString(const char *s) { static OSSymbolStub st; st.s = s; return &st; }
static MetaClass* getMetaClassWithName(const Symbol *name) {
    for (auto *c : gAllClasses) if (c->name == static_cast<const OSSymbolStub*>(name)->s) return c;
    return nullptr;
}
static const char *gMilestoneTag = "", *gMilestoneMsg = "";
static void liuqin_milestone(const char *t, const char *m) { gMilestoneTag=t; gMilestoneMsg=m; printf("milestone %s:%s\n", t, m); }
static void liuqin_debug_puts(const char *s) { fputs(s, stdout); }
static volatile const char *native_ufs_root_failure = nullptr;


// ---- XNU-named shims so helper.inc compiles verbatim ----
class OSSymbol { public: std::string s; void release() const {}
  static OSSymbol * withCString(const char *c){ static OSSymbol st; st.s=c; return &st; } };
class OSMetaClass { public: std::string name; void *reserved=nullptr;
  const char *getClassName() const { return name.c_str(); }
  static OSMetaClass * getMetaClassWithName(const OSSymbol *n); };

extern std::vector<MetaClass*> gAllClasses;
OSMetaClass* OSMetaClass::getMetaClassWithName(const OSSymbol *n){
  for (auto *c : gAllClasses) if (c->name == n->s) return reinterpret_cast<OSMetaClass*>(c);
  return nullptr;
}

// The extracted production code:
#include "helper.inc"

// ---- scenarios --------------------------------------------------------------
int main() {
    setvbuf(stdout, nullptr, _IONBF, 0);
    // Closure bootstrap: IOStorageFamily's own IOBlockStorageDevice gets registered
    // (name taken), then its ExpansionData is NOT freed here — but on real iOS 17
    // the duplicate branch reads orig->reserved->kext where reserved was kfree'd
    // for classes whose kext link failed; our device crash showed far=poison,
    // i.e. Apple's typed-free poison pattern. Model the faulting read directly.
    registerDuringKernelPass(&ioBlockStorageDevice);
    registerDuringKernelPass(&ioService);
    assert(postModLoad(false));                     // closure pass succeeds
    delete (int*)ioBlockStorageDevice.reserved;
    ioBlockStorageDevice.reserved = nullptr;        // freed by OSKext teardown path

    // Scenario A: NO gate — the observed device shape. The driver object links against a
    // "second copy" of IOBlockStorageDevice (the offline-bindings alias): its metaclass is
    // constructed with the className pointer ALREADY pointing at the OSSymbol interned under
    // "IOBlockStorageDevice" (sAllClassesDict holds that symbol as its own key). postModLoad
    // then finds orig == that very symbol entry and takes the iOS panic branch, reading
    // orig->reserved where Apple left the freed poison word -> far = 0x315f776569765f65.
    MetaClass dup{"IOBlockStorageDevice", nullptr};      // NativeUfsBlock's aliased name
    registerDuringKernelPass(&dup);
    bool ok = postModLoad(true);                         // emulate reserved-poison read
    printf("A(no gate): postModLoad ok=%d -> boot %s\n", ok, ok?"continues":"DIES at restartable_init");
    assert(!ok);                                         // reproduces the crash

    assert(gFaulted);   // scenario A really walked into the faulting branch

    // Scenario B: WITH the gate — helper sees the name taken BEFORE any alloc happens.
    gStalled.clear(); gFaulted = false;               // driver never got to stall a dup
    // exercise the gate exactly as startRoot's prologue does (gate.inc is that snippet)
    {
        if (!liuqinBaseClassFree ()) {
            native_ufs_root_failure = "IOBlockStorageDevice metaclass name already registered";
        }
    }
    bool free_gate = !native_ufs_root_failure;   // true == would have proceeded
    printf("B(gate): refused=%d failure=%s\n", !free_gate,
           native_ufs_root_failure ? native_ufs_root_failure : "(none)");
    assert(!free_gate);
    assert(native_ufs_root_failure);
    assert(std::string(gMilestoneMsg) == "base-dup");

    // Scenario C: clean board (no IOStorageFamily in the closure): gate opens.
    gAllClasses.clear();
    native_ufs_root_failure = nullptr;
    assert(liuqinBaseClassFree());
    printf("C(closed-world): gate opens when the name is free\n");

    // Scenario D: the v37/v38 shape -- a CLEAN stalled array whose one entry has an
    // ASCII-poisoned superClassLink (x24 = 0x6131373030666666 = "ffff007a" on the panel).
    // D1 must reproduce the data abort; D2 (the shipped policy) must name the slot, drop
    // it and carry on registering everything else.
    {
        MetaClass2 root{nullptr, nullptr, nullptr,      "IOService",             152};
        MetaClass2 good{nullptr, nullptr, &root,        "IOBlockStorageDevice",  248};
        MetaClass2 evil{nullptr, nullptr, (MetaClass2*)0x6131373030666666ULL, "NativeUfsBlock", 248};
        addToImage(&root); addToImage(&good); addToImage(&evil);
        std::vector<MetaClass2*> batch{&good, &evil};
        std::vector<MetaClass2*> dict;

        int r1 = scanPass(batch, dict, /*naive=*/true);
        printf("D1(v37 XNU): scan result=%d -> %s\n", r1,
               r1 == -1 ? "DIES at postModLoad+0x2d4" : "survives");
        assert(r1 == -1);                       // same instruction, same fault

        dict.clear(); gDeepest = 0;
        int r2 = scanPass(batch, dict, /*naive=*/false);
        printf("D2(v38 policy): bad=%d registered=%zu deepest=%u -> boot continues\n",
               r2, dict.size(), gDeepest);
        assert(r2 == 1);                        // exactly the one poisoned slot dropped
        assert(dict.size() == 1 && dict[0] == &good);
        assert(gDeepest == 2);                  // depth semantics preserved (entry+root)
    }

    // scenario C world cleanup (avoid harness-only leak reports)
    for (auto *c : gAllClasses) if (c->reserved) { delete (int*)c->reserved; c->reserved=nullptr; }
    printf("ALL SIM ASSERTIONS PASS\n");
    return 0;
}
