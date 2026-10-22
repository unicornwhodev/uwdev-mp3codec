// SPDX-License-Identifier: MIT
plugins {
    id("com.android.library") version "8.11.1" apply false
    id("com.android.application") version "8.11.1" apply false
    id("org.jetbrains.kotlin.android") version "2.2.21" apply false
}

tasks.wrapper {
    gradleVersion = "8.13"
    distributionType = Wrapper.DistributionType.BIN
}
