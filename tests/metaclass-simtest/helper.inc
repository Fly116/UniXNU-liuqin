static bool liuqinBaseClassFree (void)
{
  const OSSymbol *name = OSSymbol::withCString ("IOBlockStorageDevice");
  if (!name) {
    liuqin_milestone ("U", "base-symfail");   // cannot observe: stay closed
    return false;
  }
  const OSMetaClass *existing = OSMetaClass::getMetaClassWithName (name);
  name->release ();
  if (existing) {
    char line[128];
    __builtin_snprintf (line, sizeof line,
        "NativeUfs: IOBlockStorageDevice is already registered as %s; root publication refused\n",
        existing->getClassName ());
    liuqin_debug_puts (line);   // H11: panel milestone console, never the silent KDB path
    liuqin_milestone ("U", "base-dup");
    return false;
  }
  return true;
}
