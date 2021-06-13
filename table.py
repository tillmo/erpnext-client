import PySimpleGUI as sg
import csv
import report
import utils
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
import reportlab.platypus as pl
from reportlab.rl_config import defaultPageSize
from reportlab.lib.units import inch
PAGE_HEIGHT=defaultPageSize[1]
PAGE_WIDTH=defaultPageSize[0]


def myFirstPage(title):
    def myPage(canvas, doc):
        canvas.saveState()
        canvas.setTitle(title)
        canvas.setFont('Helvetica-Bold',16)
        canvas.drawCentredString(PAGE_WIDTH/2.0, PAGE_HEIGHT-108, title)
        canvas.setFont('Helvetica',9)
        canvas.drawString(PAGE_WIDTH/2.0, 0.75 * inch, " %d " % doc.page)
        canvas.restoreState()
    return myPage    

def myLaterPages(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica',9)
    canvas.drawString(PAGE_WIDTH/2.0, 0.75 * inch, " %d " % doc.page)
    canvas.restoreState()
    
class Table:
    def __init__(self,entries,keys,headings,title,enable_events=False,max_col_width=60,
                 display_row_numbers=False,filename=None):
        # table data, as list of dicts
        self.entries = entries
        # column headings for display
        self.headings = headings
        # dict keys for columns
        self.keys = keys
        self.title = title
        self.enable_events = enable_events
        self.max_col_width = max_col_width
        self.display_row_numbers = display_row_numbers
        self.filename = filename
        self.data = [[utils.to_str(utils.get(e,k)) for k in self.keys] for e in self.entries]

    def csv_export(self):
        with open(self.filename, mode='w') as f:
            writer = csv.writer(f, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writerow(self.headings)
            writer.writerows(self.data)
        print(self.filename," exportiert")    

    def pdf_export(self):
        # layout
        grid = [('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
                ('BOX', (0,0), (-1,-1), 0.25, colors.black),
                ('ALIGN',(1,0),(-1,-1),'RIGHT'),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold')]
        # typeset some rows in bold
        for i in range(len(self.entries)):
            e = self.entries[i]
            if not 'bold' in e:
                continue
            if not 'indent' in e:
                grid.append(('FONTNAME',(0,i+1),(-1,i+1),'Helvetica-Bold'))
            elif e['indent'] == 1:
                grid.append(('FONTNAME',(0,i+1),(-1,i+1),'Helvetica-BoldOblique'))
            elif e['indent'] >= 2:
                grid.append(('FONTNAME',(0,i+1),(-1,i+1),'Helvetica-Oblique'))
        # build list of 'Flowable' objects
        elements = []
        elements.append(pl.Spacer(1,0.8*inch))
        t=pl.Table([self.headings]+self.data)
        t.setStyle(pl.TableStyle(grid))
        elements.append(t)
        ## render document and write it to disk
        doc = pl.SimpleDocTemplate(self.filename)
        doc.build(elements,
                  onFirstPage=myFirstPage(self.title),
                  onLaterPages=myLaterPages)
        print(self.filename," exportiert")    

    def window(self):
        row_colors = []
        for i in range(len(self.entries)):
            if 'bold' in self.entries[i]:
                row_colors.append((i,"#f5eace"))
        layout = [[sg.SaveAs(button_text = 'CSV-Export', 
                             default_extension = 'csv',enable_events=True),
                   sg.SaveAs(button_text = 'PDF-Export', 
                             default_extension = 'pdf',enable_events=True)],
                  [sg.Table(values=self.data, headings=self.headings,
                   max_col_width=self.max_col_width,
                   auto_size_columns=len(self.data) > 0,
                   display_row_numbers=self.display_row_numbers,
                   justification='left',
                   num_rows=30,
                   key='-TABLE-',
                   enable_events=self.enable_events,
                   background_color = "lightgrey",
                   alternating_row_color = "white",
                   #header_background_color = None,
                   row_colors = row_colors,
                   row_height=25)]]
        return sg.Window(self.title, layout, finalize=True)

    def display(self):
        window = self.window()
        window.bring_to_front()
        while True:
            (event,values) = window.read()
            #print(event,values)
            if event == 'PDF-Export':   # strange, but PDF and CSV are swappeed here!
                if values['CSV-Export']:
                    self.filename = values['CSV-Export']
                    self.csv_export()
                continue
            if event == 'CSV-Export':
                if values['PDF-Export']:
                    self.filename = values['PDF-Export']
                if self.filename:    
                    self.pdf_export()
                continue
            elif event == '-TABLE-':
                ix = values['-TABLE-'][0]
                if 'disabled' in self.entries[ix] and self.entries[ix]['disabled']:
                    continue
                else:
                    window.close()
                    return ix
            break
        window.close()
        return False

    
