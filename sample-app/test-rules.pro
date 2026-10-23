# SPDX-License-Identifier: MIT
# Only the test APK: Error Prone's IncompatibleModifiers is a compiler annotation.
# Its enum refers to the JDK compiler model, which is not part of the Android runtime.
-dontwarn javax.lang.model.element.Modifier
