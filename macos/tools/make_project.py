"""Writes macos/PointeMac.xcodeproj/project.pbxproj: python3 macos/tools/make_project.py

The project is small and regular (three targets, each a folder Xcode keeps in step with the disk, and the local
PointeKit package), so it is written from this description instead of being edited by hand. Xcode can open and change
it; run this again only to change the structure. The ids are fixed, so a rerun changes nothing it does not mean to.
"""

from pathlib import Path

VERSION, BUILD = "1.16.3", "6"


def i(n: int) -> str:
    return f"B0C1D2E3F4A5{n:012X}"


PROJECT, MAIN_GROUP, PRODUCTS = i(1), i(2), i(3)
APP, TESTS, UITESTS = i(4), i(5), i(6)
APP_DIR, TESTS_DIR, UITESTS_DIR = i(7), i(8), i(9)
APP_PRODUCT, TESTS_PRODUCT, UITESTS_PRODUCT = i(10), i(11), i(12)
PHASES = {t: (i(20 + 3 * k), i(21 + 3 * k), i(22 + 3 * k)) for k, t in enumerate((APP, TESTS, UITESTS))}
PACKAGE, KIT, MACKIT, KIT_FILE, MACKIT_FILE = i(40), i(41), i(42), i(43), i(44)
PROXY_T, PROXY_U, DEP_T, DEP_U = i(50), i(51), i(52), i(53)
LISTS = {"project": i(60), APP: i(61), TESTS: i(62), UITESTS: i(63)}
CONFIGS = {(o, c): i(70 + 2 * k + j) for k, o in enumerate(("project", APP, TESTS, UITESTS)) for j, c in enumerate(("Debug", "Release"))}
EXCEPTIONS = i(90)

COMMON = {
    "ALWAYS_SEARCH_USER_PATHS": "NO", "CLANG_ENABLE_MODULES": "YES", "CLANG_ENABLE_OBJC_ARC": "YES",
    "ENABLE_USER_SCRIPT_SANDBOXING": "YES", "GCC_NO_COMMON_BLOCKS": "YES", "MACOSX_DEPLOYMENT_TARGET": "14.0",
    "SDKROOT": "macosx", "SWIFT_VERSION": "6.0", "SWIFT_STRICT_CONCURRENCY": "complete",
    "GCC_WARN_UNUSED_VARIABLE": "YES", "CLANG_WARN_SUSPICIOUS_MOVE": "YES", "LOCALIZATION_PREFERS_STRING_CATALOGS": "YES",
    "SWIFT_EMIT_LOC_STRINGS": "YES", "DEAD_CODE_STRIPPING": "YES",
}
DEBUG = {"DEBUG_INFORMATION_FORMAT": "dwarf", "ENABLE_TESTABILITY": "YES", "ONLY_ACTIVE_ARCH": "YES", "GCC_OPTIMIZATION_LEVEL": "0",
         "SWIFT_OPTIMIZATION_LEVEL": '"-Onone"', "SWIFT_ACTIVE_COMPILATION_CONDITIONS": '"DEBUG $(inherited)"',
         "GCC_PREPROCESSOR_DEFINITIONS": '("DEBUG=1", "$(inherited)")'}
RELEASE = {"DEBUG_INFORMATION_FORMAT": '"dwarf-with-dsym"', "SWIFT_COMPILATION_MODE": "wholemodule", "VALIDATE_PRODUCT": "YES"}
APP_SETTINGS = {
    "ASSETCATALOG_COMPILER_APPICON_NAME": "AppIcon", "ASSETCATALOG_COMPILER_GLOBAL_ACCENT_COLOR_NAME": "AccentColor",
    "CODE_SIGN_ENTITLEMENTS": "PointeMac/PointeMac.entitlements", "CODE_SIGN_STYLE": "Automatic", '"CODE_SIGN_IDENTITY"': '"-"',
    "COMBINE_HIDPI_IMAGES": "YES", "CURRENT_PROJECT_VERSION": BUILD, "DEVELOPMENT_TEAM": '""', "ENABLE_HARDENED_RUNTIME": "YES",
    "GENERATE_INFOPLIST_FILE": "YES", "INFOPLIST_FILE": "PointeMac/Info.plist",
    "INFOPLIST_KEY_CFBundleDisplayName": "Pointe", "INFOPLIST_KEY_LSApplicationCategoryType": '"public.app-category.developer-tools"',
    "INFOPLIST_KEY_NSHumanReadableCopyright": '"MIT, © Ballerine"',
    "LD_RUNPATH_SEARCH_PATHS": '("$(inherited)", "@executable_path/../Frameworks")', "MARKETING_VERSION": VERSION,
    "PRODUCT_BUNDLE_IDENTIFIER": "io.ballerine.pointe.mac", "PRODUCT_NAME": "Pointe", "SWIFT_EMIT_LOC_STRINGS": "YES",
}
TEST_SETTINGS = {
    "BUNDLE_LOADER": '"$(TEST_HOST)"', "CODE_SIGN_STYLE": "Automatic", '"CODE_SIGN_IDENTITY"': '"-"', "CURRENT_PROJECT_VERSION": BUILD,
    "DEVELOPMENT_TEAM": '""', "GENERATE_INFOPLIST_FILE": "YES", "MARKETING_VERSION": VERSION,
    "PRODUCT_BUNDLE_IDENTIFIER": "io.ballerine.pointe.mac.tests", "PRODUCT_NAME": '"$(TARGET_NAME)"',
    "TEST_HOST": '"$(BUILT_PRODUCTS_DIR)/Pointe.app/Contents/MacOS/Pointe"',
}
UITEST_SETTINGS = {
    "CODE_SIGN_STYLE": "Automatic", '"CODE_SIGN_IDENTITY"': '"-"', "CURRENT_PROJECT_VERSION": BUILD, "DEVELOPMENT_TEAM": '""',
    "GENERATE_INFOPLIST_FILE": "YES", "MARKETING_VERSION": VERSION, "PRODUCT_BUNDLE_IDENTIFIER": "io.ballerine.pointe.mac.uitests",
    "PRODUCT_NAME": '"$(TARGET_NAME)"', "TEST_TARGET_NAME": "PointeMac",
}


def settings(values: dict) -> str:
    return "".join(f"\t\t\t\t{k} = {v};\n" for k, v in sorted(values.items()))


def config(owner: str, name: str, values: dict) -> str:
    return (f"\t\t{CONFIGS[(owner, name)]} /* {name} */ = {{\n\t\t\tisa = XCBuildConfiguration;\n\t\t\tbuildSettings = {{\n"
            f"{settings(values)}\t\t\t}};\n\t\t\tname = {name};\n\t\t}};\n")


def config_list(owner: str, label: str) -> str:
    return (f"\t\t{LISTS[owner]} /* Build configuration list for {label} */ = {{\n\t\t\tisa = XCConfigurationList;\n"
            f"\t\t\tbuildConfigurations = (\n\t\t\t\t{CONFIGS[(owner, 'Debug')]} /* Debug */,\n\t\t\t\t{CONFIGS[(owner, 'Release')]} /* Release */,\n"
            f"\t\t\t);\n\t\t\tdefaultConfigurationIsVisible = 0;\n\t\t\tdefaultConfigurationName = Release;\n\t\t}};\n")


def target(tid: str, name: str, folder: str, product: str, product_name: str, kind: str, deps: str = "", packages: str = "") -> str:
    sources, frameworks, resources = PHASES[tid]
    return (f"\t\t{tid} /* {name} */ = {{\n\t\t\tisa = PBXNativeTarget;\n\t\t\tbuildConfigurationList = {LISTS[tid]};\n"
            f"\t\t\tbuildPhases = (\n\t\t\t\t{sources} /* Sources */,\n\t\t\t\t{frameworks} /* Frameworks */,\n\t\t\t\t{resources} /* Resources */,\n\t\t\t);\n"
            f"\t\t\tbuildRules = (\n\t\t\t);\n\t\t\tdependencies = (\n{deps}\t\t\t);\n"
            f"\t\t\tfileSystemSynchronizedGroups = (\n\t\t\t\t{folder} /* {name} */,\n\t\t\t);\n\t\t\tname = {name};\n"
            f"\t\t\tpackageProductDependencies = (\n{packages}\t\t\t);\n\t\t\tproductName = {name};\n"
            f"\t\t\tproductReference = {product} /* {product_name} */;\n\t\t\tproductType = \"{kind}\";\n\t\t}};\n")


def phase(pid: str, isa: str, files: str = "") -> str:
    return (f"\t\t{pid} /* {isa} */ = {{\n\t\t\tisa = {isa};\n\t\t\tbuildActionMask = 2147483647;\n\t\t\tfiles = (\n{files}\t\t\t);\n"
            f"\t\t\trunOnlyForDeploymentPostprocessing = 0;\n\t\t}};\n")


def project() -> str:
    out = ["// !$*UTF8*$!\n{\n\tarchiveVersion = 1;\n\tclasses = {\n\t};\n\tobjectVersion = 77;\n\tobjects = {\n\n"]
    out.append(f"\t\t{KIT_FILE} /* PointeKit in Frameworks */ = {{isa = PBXBuildFile; productRef = {KIT} /* PointeKit */; }};\n")
    out.append(f"\t\t{MACKIT_FILE} /* PointeMacKit in Frameworks */ = {{isa = PBXBuildFile; productRef = {MACKIT} /* PointeMacKit */; }};\n")
    for proxy in (PROXY_T, PROXY_U):
        out.append(f"\t\t{proxy} /* PBXContainerItemProxy */ = {{\n\t\t\tisa = PBXContainerItemProxy;\n\t\t\tcontainerPortal = {PROJECT} /* Project object */;\n"
                   f"\t\t\tproxyType = 1;\n\t\t\tremoteGlobalIDString = {APP};\n\t\t\tremoteInfo = PointeMac;\n\t\t}};\n")
    out.append(f"\t\t{APP_PRODUCT} /* Pointe.app */ = {{isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = Pointe.app; sourceTree = BUILT_PRODUCTS_DIR; }};\n")
    out.append(f"\t\t{TESTS_PRODUCT} /* PointeMacTests.xctest */ = {{isa = PBXFileReference; explicitFileType = wrapper.cfbundle; includeInIndex = 0; path = PointeMacTests.xctest; sourceTree = BUILT_PRODUCTS_DIR; }};\n")
    out.append(f"\t\t{UITESTS_PRODUCT} /* PointeMacUITests.xctest */ = {{isa = PBXFileReference; explicitFileType = wrapper.cfbundle; includeInIndex = 0; path = PointeMacUITests.xctest; sourceTree = BUILT_PRODUCTS_DIR; }};\n")
    out.append(f"\t\t{EXCEPTIONS} /* Exceptions for \"PointeMac\" folder in \"PointeMac\" target */ = {{\n\t\t\tisa = PBXFileSystemSynchronizedBuildFileExceptionSet;\n"
               f"\t\t\tmembershipExceptions = (\n\t\t\t\tInfo.plist,\n\t\t\t\tPointeMac.entitlements,\n\t\t\t);\n\t\t\ttarget = {APP} /* PointeMac */;\n\t\t}};\n")
    out.append(f"\t\t{APP_DIR} /* PointeMac */ = {{\n\t\t\tisa = PBXFileSystemSynchronizedRootGroup;\n\t\t\texceptions = (\n\t\t\t\t{EXCEPTIONS},\n\t\t\t);\n\t\t\tpath = PointeMac;\n\t\t\tsourceTree = \"<group>\";\n\t\t}};\n")
    for gid, name in ((TESTS_DIR, "PointeMacTests"), (UITESTS_DIR, "PointeMacUITests")):
        out.append(f"\t\t{gid} /* {name} */ = {{\n\t\t\tisa = PBXFileSystemSynchronizedRootGroup;\n\t\t\tpath = {name};\n\t\t\tsourceTree = \"<group>\";\n\t\t}};\n")
    out.append(phase(PHASES[APP][1], "PBXFrameworksBuildPhase", f"\t\t\t\t{KIT_FILE} /* PointeKit in Frameworks */,\n\t\t\t\t{MACKIT_FILE} /* PointeMacKit in Frameworks */,\n"))
    out.append(phase(PHASES[TESTS][1], "PBXFrameworksBuildPhase"))
    out.append(phase(PHASES[UITESTS][1], "PBXFrameworksBuildPhase"))
    out.append(f"\t\t{MAIN_GROUP} = {{\n\t\t\tisa = PBXGroup;\n\t\t\tchildren = (\n\t\t\t\t{APP_DIR} /* PointeMac */,\n\t\t\t\t{TESTS_DIR} /* PointeMacTests */,\n"
               f"\t\t\t\t{UITESTS_DIR} /* PointeMacUITests */,\n\t\t\t\t{PRODUCTS} /* Products */,\n\t\t\t);\n\t\t\tsourceTree = \"<group>\";\n\t\t}};\n")
    out.append(f"\t\t{PRODUCTS} /* Products */ = {{\n\t\t\tisa = PBXGroup;\n\t\t\tchildren = (\n\t\t\t\t{APP_PRODUCT} /* Pointe.app */,\n\t\t\t\t{TESTS_PRODUCT} /* PointeMacTests.xctest */,\n"
               f"\t\t\t\t{UITESTS_PRODUCT} /* PointeMacUITests.xctest */,\n\t\t\t);\n\t\t\tname = Products;\n\t\t\tsourceTree = \"<group>\";\n\t\t}};\n")
    out.append(target(APP, "PointeMac", APP_DIR, APP_PRODUCT, "Pointe.app", "com.apple.product-type.application",
                      packages=f"\t\t\t\t{KIT} /* PointeKit */,\n\t\t\t\t{MACKIT} /* PointeMacKit */,\n"))
    out.append(target(TESTS, "PointeMacTests", TESTS_DIR, TESTS_PRODUCT, "PointeMacTests.xctest", "com.apple.product-type.bundle.unit-test",
                      deps=f"\t\t\t\t{DEP_T} /* PBXTargetDependency */,\n"))
    out.append(target(UITESTS, "PointeMacUITests", UITESTS_DIR, UITESTS_PRODUCT, "PointeMacUITests.xctest", "com.apple.product-type.bundle.ui-testing",
                      deps=f"\t\t\t\t{DEP_U} /* PBXTargetDependency */,\n"))
    out.append(f"\t\t{PROJECT} /* Project object */ = {{\n\t\t\tisa = PBXProject;\n\t\t\tattributes = {{\n\t\t\t\tBuildIndependentTargetsInParallel = 1;\n"
               f"\t\t\t\tLastSwiftUpdateCheck = 2700;\n\t\t\t\tLastUpgradeCheck = 2700;\n\t\t\t\tTargetAttributes = {{\n"
               f"\t\t\t\t\t{APP} = {{\n\t\t\t\t\t\tCreatedOnToolsVersion = 27.0;\n\t\t\t\t\t}};\n"
               f"\t\t\t\t\t{TESTS} = {{\n\t\t\t\t\t\tCreatedOnToolsVersion = 27.0;\n\t\t\t\t\t\tTestTargetID = {APP};\n\t\t\t\t\t}};\n"
               f"\t\t\t\t\t{UITESTS} = {{\n\t\t\t\t\t\tCreatedOnToolsVersion = 27.0;\n\t\t\t\t\t\tTestTargetID = {APP};\n\t\t\t\t\t}};\n\t\t\t\t}};\n\t\t\t}};\n"
               f"\t\t\tbuildConfigurationList = {LISTS['project']};\n\t\t\tdevelopmentRegion = en;\n\t\t\thasScannedForEncodings = 0;\n"
               f"\t\t\tknownRegions = (\n\t\t\t\ten,\n\t\t\t\tBase,\n\t\t\t);\n\t\t\tmainGroup = {MAIN_GROUP};\n\t\t\tminimizedProjectReferenceProxies = 1;\n"
               f"\t\t\tpackageReferences = (\n\t\t\t\t{PACKAGE} /* XCLocalSwiftPackageReference \"../apple/PointeKit\" */,\n\t\t\t);\n"
               f"\t\t\tpreferredProjectObjectVersion = 77;\n\t\t\tproductRefGroup = {PRODUCTS} /* Products */;\n\t\t\tprojectDirPath = \"\";\n\t\t\tprojectRoot = \"\";\n"
               f"\t\t\ttargets = (\n\t\t\t\t{APP} /* PointeMac */,\n\t\t\t\t{TESTS} /* PointeMacTests */,\n\t\t\t\t{UITESTS} /* PointeMacUITests */,\n\t\t\t);\n\t\t}};\n")
    for tid in (APP, TESTS, UITESTS):
        out.append(phase(PHASES[tid][2], "PBXResourcesBuildPhase"))
        out.append(phase(PHASES[tid][0], "PBXSourcesBuildPhase"))
    for dep, proxy in ((DEP_T, PROXY_T), (DEP_U, PROXY_U)):
        out.append(f"\t\t{dep} /* PBXTargetDependency */ = {{\n\t\t\tisa = PBXTargetDependency;\n\t\t\ttarget = {APP} /* PointeMac */;\n\t\t\ttargetProxy = {proxy} /* PBXContainerItemProxy */;\n\t\t}};\n")
    out.append(config("project", "Debug", {**COMMON, **DEBUG}))
    out.append(config("project", "Release", {**COMMON, **RELEASE}))
    for owner, values in ((APP, APP_SETTINGS), (TESTS, TEST_SETTINGS), (UITESTS, UITEST_SETTINGS)):
        out.append(config(owner, "Debug", values))
        out.append(config(owner, "Release", values))
    out.append(config_list("project", 'PBXProject "PointeMac"'))
    for owner, label in ((APP, "PointeMac"), (TESTS, "PointeMacTests"), (UITESTS, "PointeMacUITests")):
        out.append(config_list(owner, f'PBXNativeTarget "{label}"'))
    out.append(f"\t\t{PACKAGE} /* XCLocalSwiftPackageReference \"../apple/PointeKit\" */ = {{\n\t\t\tisa = XCLocalSwiftPackageReference;\n\t\t\trelativePath = ../apple/PointeKit;\n\t\t}};\n")
    for pid, name in ((KIT, "PointeKit"), (MACKIT, "PointeMacKit")):
        out.append(f"\t\t{pid} /* {name} */ = {{\n\t\t\tisa = XCSwiftPackageProductDependency;\n\t\t\tproductName = {name};\n\t\t}};\n")
    out.append(f"\t}};\n\trootObject = {PROJECT} /* Project object */;\n}}\n")
    return "".join(out)


SCHEME = f"""<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion = "2700" version = "1.7">
   <BuildAction parallelizeBuildables = "YES" buildImplicitDependencies = "YES">
      <BuildActionEntries>
         <BuildActionEntry buildForTesting = "YES" buildForRunning = "YES" buildForProfiling = "YES" buildForArchiving = "YES" buildForAnalyzing = "YES">
            <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "{APP}" BuildableName = "Pointe.app" BlueprintName = "PointeMac" ReferencedContainer = "container:PointeMac.xcodeproj"></BuildableReference>
         </BuildActionEntry>
      </BuildActionEntries>
   </BuildAction>
   <TestAction buildConfiguration = "Debug" selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv = "YES">
      <Testables>
         <TestableReference skipped = "NO">
            <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "{TESTS}" BuildableName = "PointeMacTests.xctest" BlueprintName = "PointeMacTests" ReferencedContainer = "container:PointeMac.xcodeproj"></BuildableReference>
         </TestableReference>
         <TestableReference skipped = "NO">
            <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "{UITESTS}" BuildableName = "PointeMacUITests.xctest" BlueprintName = "PointeMacUITests" ReferencedContainer = "container:PointeMac.xcodeproj"></BuildableReference>
         </TestableReference>
      </Testables>
   </TestAction>
   <LaunchAction buildConfiguration = "Debug" selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB" launchStyle = "0" useCustomWorkingDirectory = "NO" ignoresPersistentStateOnLaunch = "NO" debugDocumentVersioning = "YES" debugServiceExtension = "internal" allowLocationSimulation = "YES">
      <BuildableProductRunnable runnableDebuggingMode = "0">
         <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "{APP}" BuildableName = "Pointe.app" BlueprintName = "PointeMac" ReferencedContainer = "container:PointeMac.xcodeproj"></BuildableReference>
      </BuildableProductRunnable>
   </LaunchAction>
   <ArchiveAction buildConfiguration = "Release" revealArchiveInOrganizer = "YES"></ArchiveAction>
</Scheme>
"""

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1] / "PointeMac.xcodeproj"
    (root / "xcshareddata" / "xcschemes").mkdir(parents=True, exist_ok=True)
    (root / "project.pbxproj").write_text(project())
    (root / "xcshareddata" / "xcschemes" / "PointeMac.xcscheme").write_text(SCHEME)
    print("wrote", root)
