import csv
import re

VAT_RATES = [0.07,0.16,0.19]

def extract_numbers(s):
    numbers = re.findall(r"([0-9]+,[0-9][0-9])",s)
    return list(map(lambda s: float(s.replace(",",".")),numbers))
    
def extract_amount(filename,rate):
    f = open(filename,'r')
    contents = f.read()
    f.close()
    numbers = extract_numbers(contents)
    amount = max(numbers)
    for vat_rate in VAT_RATES:
        vat = round(amount / (1+vat_rate) * vat_rate,2)
        #print(vat)
        if vat in numbers:
            return(vat,amount)
    # mwst_lines = [l for l in contents.split("\n") if "mwst" in l.lower]
    
    # for line in f.readlines():
    #     line = line.lower()
    #     numbers = re.findall(r"([0-9]+,[0-9][0-9])",line)
    #     numbers = list(map(lambda s: float(s.replace(",",".")),numbers))
    #     if "mwst" in line:
    #         print("m",end=" ")
    #     if numbers:
    #         print(numbers)
    #     if "mwst" in line:
    #         mwst_guess = min(numbers+[1000000]) 
    # #print(numbers)
    # #lines = f.readlines()
    # #print(lines)
    return (0,amount)

def check(filename):
    mwst = None
    amount = None
    with open(filename+'.csv','r') as csvfile:
        for row in csv.reader(csvfile, delimiter=','):
            mwst = float(row[0])
            amount = float(row[1])
    rate = mwst/(amount-mwst)
    if abs(rate-0.19)>0.001 and abs(rate-0.16)>0.001 and rate: 
        print(rate)
    rate = round(rate,2)
    (m1,a1) = extract_amount(filename+".txt",rate)    
    (m2,a2) = extract_amount(filename+"-raw.txt",rate)
    print("{:3}".format(filename),end=" ")
    if not (amount==a1 and amount==a2):
        print("a {: >6.2f} {: >6.2f} {: >6.2f}".format(amount,a1,a2),end=" ")
    if not (mwst==m1 and mwst==m2):
        print("m {: >6.2f} {: >6.2f} {: >6.2f}".format(mwst,m1,m2),end=" ")
    print()    
    
for i in [1,2,3,4,5,6,13,15,16]:
    check(str(i))

#for i in [17,18,19]:
#    check("test/"+str(i))
    
