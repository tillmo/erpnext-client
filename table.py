import PySimpleGUI as sg
import csv
import report
import utils
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
import reportlab.platypus as pl
from reportlab.rl_config import defaultPageSize
from reportlab.lib.units import inch
PAGE_HEIGHT=defaultPageSize[1]
PAGE_WIDTH=defaultPageSize[0]


def myFirstPage(title,page_height,page_width):
    def myPage(canvas, doc):
        canvas.saveState()
        canvas.setTitle(title)
        canvas.setFont('Helvetica-Bold',16)
        canvas.drawCentredString(page_width/2.0, page_height-108, title)
        canvas.setFont('Helvetica',9)
        canvas.drawString(page_width/2.0, 0.75 * inch, " %d " % doc.page)
        canvas.restoreState()
    return myPage    

def myLaterPages(page_height,page_width):
    def myPage(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica',9)
        canvas.drawString(page_width/2.0, 0.75 * inch, " %d " % doc.page)
        canvas.restoreState()
    return myPage    
    
class Table:
    def __init__(self,entries,keys,headings,title,enable_events=False,max_col_width=60,
                 display_row_numbers=False,filename=None,child=None,child_title=None,just='left',landscape=False):
        # table data, as list of dicts
        self.entries = entries
        # column headings for display
        self.headings = headings
        # dict keys for columns
        self.keys = keys
        # justification
        self.just = just
        self.title = title
        self.enable_events = enable_events
        self.max_col_width = max_col_width
        self.display_row_numbers = display_row_numbers
        self.filename = filename
        self.data = [[utils.to_str(utils.get(e,k)) for k in self.keys] for e in self.entries]
        # for display of several tables in one PDF
        self.child = child
        self.child_title = child_title # button display
        self.landscape = landscape
        self.set_format()

    def set_format(self):    
        self.page_height = A4[0] if self.landscape else A4[1]
        self.page_width = A4[1] if self.landscape else A4[0]

    def csv_export(self):
        with open(self.filename, mode='w') as f:
            writer = csv.writer(f, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writerow(self.headings)
            writer.writerows(self.data)
        print(self.filename," exportiert")    

    def pdf_elements(self):
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
            if e['bold'] == 3:
                grid.append(('FONTNAME',(0,i+1),(-1,i+1),'Helvetica-Bold'))
            elif e['bold'] == 2:
                grid.append(('FONTNAME',(0,i+1),(-1,i+1),'Helvetica-BoldOblique'))
            elif e['bold'] >= 1:
                grid.append(('FONTNAME',(0,i+1),(-1,i+1),'Helvetica-Oblique'))
        # build list of 'Flowable' objects
        elements = []
        elements.append(pl.Spacer(1,0.8*inch))
        t=pl.Table([self.headings]+self.data)
        t.setStyle(pl.TableStyle(grid))
        elements.append(t)
        return elements
    
    def pdf_export(self,with_child=False,landscape=False):
        self.landscape = (self.landscape or landscape)
        self.set_format()
        doc = pl.SimpleDocTemplate(self.filename,
                                   pagesize=(self.page_width,self.page_height))
        elements = self.pdf_elements()
        if with_child and self.child:
            elements += self.child.pdf_elements()
        ## write document to disk
        doc.build(elements,
                  onFirstPage=myFirstPage(self.title,self.page_height,self.page_width),
                  onLaterPages=myLaterPages(self.page_height,self.page_width))
        print(self.filename," exportiert")    

    def window(self):
        row_colors = []
        for i in range(len(self.entries)):
            if 'bold' in self.entries[i]:
                row_colors.append((i,"#f5eace"))
        buttons = [sg.Text(text="Exportieren als: "),
                   sg.SaveAs(button_text = 'CSV', k = 'CSV', target='CSV',
                             default_extension = 'csv',enable_events=True),
                   sg.SaveAs(button_text = 'PDF', k = 'PDF', target='PDF',
                             default_extension = 'pdf',enable_events=True),
                   sg.SaveAs(button_text = 'PDF quer', k = 'PDFl', target='PDFl',
                             default_extension = 'pdf',enable_events=True)]
        if self.child_title:
            text = 'PDF'+self.child_title
            buttons += [sg.SaveAs(button_text = text, k = 'PDF+', target='PDF+',
                                  default_extension = 'pdf',enable_events=True)]
        num_rows = max([5,min([20,len(self.entries)])])
        layout = [buttons,
                  [sg.Table(values=self.data, headings=self.headings,
                   max_col_width=self.max_col_width,
                   auto_size_columns=len(self.data) > 0,
                   display_row_numbers=self.display_row_numbers,
                   justification=self.just,
                   num_rows=num_rows,
                   font=('Helvetica',12),
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
            if event == 'CSV':
                if values['CSV']:
                    self.filename = values['CSV']
                    self.csv_export()
                continue
            elif event in ['PDF','PDFl']:
                if values[event]:
                    self.filename = values[event]
                if self.filename:    
                    self.pdf_export(landscape=event=='PDFl')
                continue
            elif event == 'PDF+':
                if values['PDF+']:
                    self.filename = values['PDF+']
                if self.filename:    
                    self.pdf_export(with_child=True)
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

    
