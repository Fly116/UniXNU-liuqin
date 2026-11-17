bool NativeUfs::startRoot (IOService *provider)
{
  const char *why = "";
  // liuqin (H16): publish nothing when IOBlockStorageDevice's metaclass name is already
  // taken (the prelinked IOStorageFamily owns it on every iOS 17 closure). Allocating the
  // first NativeUfsBlock would register a duplicate name and panic inside
  // OSMetaClass::postModLoad before any diagnostic could be shown.
  if (!liuqinBaseClassFree ()) {
    native_ufs_root_failure = "IOBlockStorageDevice metaclass name already registered";
    return false;
  }
  
