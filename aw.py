python -c "
f=open('C:/Users/azrae/android-sdk/tools/aw.py','w')
f.write('import sys,subprocess\n')
f.write('args=sys.argv[1:]\n')
f.write(\"\"\"if args==['list','targets']:
    r=subprocess.run(['sdkmanager','--list_installed'],capture_output=True,text=True)
    for l in r.stdout.splitlines():
        if 'platforms;android-' in l:
            p=l.split(';')[1].strip()
            if p.startswith('android-'):
                v=p.split('-')[1]
                print(f'id: {p}  or \\\"android-{v}\\\"  Name: Android API {v}')
elif args:
    subprocess.run(['sdkmanager']+args)
else:
    print('Use: android list targets')
\"\"\")
f.close()
print('aw.py created')
"