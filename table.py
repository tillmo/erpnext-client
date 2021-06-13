import PySimpleGUI as sg
import csv
import report
import utils

def csv_export(filename,data,headings):
    with open(filename, mode='w') as f:
        writer = csv.writer(f, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headings)
        writer.writerows(data)
    print(filename," exportiert")    

class Table:
    def __init__(self,entries,keys,headings,title,enable_events=False,max_col_width=60):
        # table data, as list of dicts
        self.entries = entries
        # column headings for display
        self.headings = headings
        # dict keys for columns
        self.keys = keys
        self.title = title
        self.enable_events = enable_events
        self.max_col_width = max_col_width
    def display(self):
        settings = sg.UserSettings()
        data = [[utils.to_str(utils.get(e,k)) for k in self.keys] for e in self.entries]
        layout = [[sg.SaveAs(button_text = 'CSV-Export',
                             default_extension = 'csv',enable_events=True)],
                  [sg.Table(values=data, headings=self.headings, max_col_width=self.max_col_width,
                   auto_size_columns=len(data) > 0,
                   display_row_numbers=True,
                   justification='left',
                   num_rows=30,
                   key='-TABLE-',
                   enable_events=self.enable_events,
                   row_height=25)]]
        window1 = sg.Window(self.title, layout, finalize=True)
        #window1.Widget.column('#3', anchor='e')
        window1.bring_to_front()
        while True:
            (event,values) = window1.read()
            #print(event,values)
            if event == 'CSV-Export':
                if values['CSV-Export']:
                    csv_export(values['CSV-Export'],data,self.headings)    
                continue
            elif event == '-TABLE-':
                ix = values['-TABLE-'][0]
                if 'disabled' in self.entries[ix] and self.entries[ix]['disabled']:
                    continue
                else:
                    window1.close()
                    return ix
            break
        window1.close()
        return False

    
