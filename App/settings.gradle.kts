pluginManagement {
    repositories {
        // 优先使用阿里云镜像
        maven {
            url = uri("https://maven.aliyun.com/repository/public/")
        }
        maven {
            url = uri("https://maven.aliyun.com/repository/google/")
        }
        maven {
            url = uri("https://maven.aliyun.com/repository/gradle-plugin/")
        }
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        // 优先使用阿里云镜像
        maven {
            url = uri("https://maven.aliyun.com/repository/public/")
        }
        maven {
            url = uri("https://maven.aliyun.com/repository/google/")
        }
        google()
        mavenCentral()
    }
}

rootProject.name = "EmpLab"
include(":app")
