import sys

path = "android/app/build.gradle"
with open(path) as f:
    content = f.read()

signing_lines = [
    "    signingConfigs {",
    "        debug {",
    '            storeFile file("../../android-plugin/spartan-debug.keystore")',
    '            storePassword "spartan123"',
    '            keyAlias "spartankey"',
    '            keyPassword "spartan123"',
    "        }",
    "    }",
]
signing_block = "\n".join(signing_lines) + "\n"

if "spartan-debug.keystore" in content:
    print("signingConfigs already present, skipping insert")
else:
    marker = "android {"
    if marker not in content:
        print("ERROR: could not find 'android {' in build.gradle")
        sys.exit(1)
    content = content.replace(marker, marker + "\n" + signing_block, 1)
    with open(path, "w") as f:
        f.write(content)
    print("signingConfigs block inserted")
