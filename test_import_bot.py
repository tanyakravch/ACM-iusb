import importlib.util
spec = importlib.util.spec_from_file_location('userbot', r'c:\Users\butte\Downloads\Discord\bot.py')
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
    print('Imported bot.py successfully')
except Exception as e:
    print('IMPORT ERROR:', type(e).__name__, e)
