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
    
def pdf_export():
    doc = SimpleDocTemplate(filename)
    ## container for the 'Flowable' objects
    elements = []
    elements.append(Spacer(1,0.8*inch))
    grid = [('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
            ('BOX', (0,0), (-1,-1), 0.25, colors.black),
            ('ALIGN',(1,0),(-1,-1),'RIGHT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold')]
    for i in range(len(report_data)):
        if i in leaves:
            continue
        r = report_data[i]
        if not 'indent' in r:
            grid.append(('FONTNAME',(0,i+1),(-1,i+1),'Helvetica-Bold'))
        elif r['indent'] == 1:
            grid.append(('FONTNAME',(0,i+1),(-1,i+1),'Helvetica-BoldOblique'))
        elif r['indent'] >= 2:
            grid.append(('FONTNAME',(0,i+1),(-1,i+1),'Helvetica-Oblique'))
    t=Table([header]+data)
    t.setStyle(TableStyle(grid))
    elements.append(format_report(company_name,'Profit and Loss Statement',
                                  start_date_str,end_date_str,
                                  periodicity=periodicity,
                                  consolidated=consolidated))
    #elements.append(PageBreak())
    elements.append(Spacer(1,0.8*inch))
    elements.append(format_report(company_name,'Balance Sheet',
                                  start_date_str,end_date_str,
                                  periodicity='Yearly',
                                  consolidated=consolidated))
    ## write the document to disk
    doc.build(elements,
              onFirstPage=myFirstPage(title),
              onLaterPages=myLaterPages)
    print("Abrechnug unter {} gespeichert".format(pdf)) 
    return filename

class Table:
    def __init__(self,entries,keys,headings,title,enable_events=False,max_col_width=60,
                 display_row_numbers=False):
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
    def display(self):
        settings = sg.UserSettings()
        data = [[utils.to_str(utils.get(e,k)) for k in self.keys] for e in self.entries]
        row_colors = []
        for i in range(len(self.entries)):
            if 'bold' in self.entries[i]:
                row_colors.append((i,"#f5eace"))
        layout = [[sg.SaveAs(button_text = 'CSV-Export',
                             default_extension = 'csv',enable_events=True)],
                  [sg.Table(values=data, headings=self.headings, max_col_width=self.max_col_width,
                   auto_size_columns=len(data) > 0,
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

    
