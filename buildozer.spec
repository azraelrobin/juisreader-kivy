[app]

android.sdk = C:\Users\azrae\android-sdk
title = JuisReader
package.name = juisreader
package.domain = com.juisreader

source.dir = .
mainmodule = main

version = 1.0.0

requirements = python3,kivy,requests,Pillow

orientation = portrait

fullscreen = 0

android.permissions = INTERNET,ACCESS_NETWORK_STATE

# 打包字体文件
source.include_exts = py,png,jpg,kv,ttc,ttf,json

[buildozer]
android.list_target_mode = fake
log_level = 2
