python -c "
f=open('C:/Users/azrae/android-sdk/tools/android.bat','w')
f.write('@echo off\r\npython \"%~dp0aw.py\" %*\r\n')
f.close()
print('android.bat created')
"