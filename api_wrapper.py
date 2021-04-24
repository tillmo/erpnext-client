import sys, tempfile, os
import re
import traceback

def function_wrapper(f,*args, **kwargs):
    stdout_tmp = tempfile.mktemp()
    stderr_tmp = tempfile.mktemp()
    stdout_f = open(stdout_tmp, "w")
    stderr_f = open(stderr_tmp, "w")
    orig_out = sys.stdout
    sys.stdout = stdout_f
    orig_err = sys.stderr
    sys.stderr = stderr_f
    ex = ""
    resource = {}
    try:
        resource = f(*args, **kwargs)
    except Exception as e:
        ex = str(e)+"\n"+traceback.format_exc()
    sys.stdout = orig_out
    sys.stderr = orig_err
    stdout_f.close()
    stderr_f.close()
    with open(stdout_tmp,'r') as stdout_f:
        out = stdout_f.read()
    with open(stderr_tmp,'r') as stderr_f:
        err = stderr_f.read()
    os.remove(stdout_tmp)    
    os.remove(stderr_tmp)
    return {'resource':resource,'exception':ex,'stdout':out,'stderr':err}

def api_wrapper(f,*args, **kwargs):
    result = function_wrapper(f,*args, **kwargs)
    html = result['stdout'].strip()
    if html:
        match=re.search("<p>([^§]*)</p>",html)
        if match:
            lines = match.group(0).split("\n")
            err_lines = [l for l in lines if "Error" in l]
            if not err_lines:
                err_line = None
                for i in range(len(lines)-1):
                    if "raise raise_exception(msg)" in lines[i]:
                        err_line = lines[i+1]
                        break
                if err_line:
                    err_lines = [err_line]
                else:    
                    err_lines = lines[0:10]+["[...]"]+lines[-15:-1]
            err_msg = "\n".join(err_lines)
        else:
            err_msg = html
    else:
        err_msg = ""
    if not err_msg.split():
        err_msg = ""
    result['err_msg'] = err_msg
    return result

def api_wrapper_test(f,*args, **kwargs):
    result = api_wrapper(f,*args, **kwargs)
    return not(result['err_msg'] or result['exception'])
    
import easygui

def gui_api_wrapper(f,*args, **kwargs):
    result = api_wrapper(f,*args, **kwargs)
    if result['err_msg'] or result['exception']:
        title = "\nFehler in Kommunikation mit dem ERPNext API\n"+\
                "Bitte Admin folgenden Text an Admin mailen\n"
        err = "{0}\n{1}\n{2}\n{2}".format("Aufruf: "+str(args)+str(kwargs),
                                     result['err_msg'],
                                     result['stderr'],
                                     result['exception'])
        print(title+err)
        return None
    return result['resource']
