# SPDX-License-Identifier: MIT
# QA-only Release target: AndroidJUnitRunner needs Kotlin runtime classes that
# the sample alone does not reach. R8 still shrinks/obfuscates application,
# export and codec classes. This file is never a consumer rule in either AAR.
-keep class kotlin.** { *; }
