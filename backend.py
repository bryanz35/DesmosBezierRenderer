import json
from flask import Flask
from flask_cors import CORS
from flask import request
from flask import render_template

from PIL import Image
import numpy as np
import potrace
import cv2

import multiprocessing
from time import time
import os
import sys
import getopt
import traceback


app = Flask(__name__, template_folder='frontend')
CORS(app)


FRAME_DIR = 'frames' # The folder where the frames are stored relative to this file
FILE_EXT = 'png' # Extension for frame files
COLOUR = '#2464b4' # Hex value of colour for graph output	

BILATERAL_FILTER = False # Reduce number of lines with bilateral filter
DOWNLOAD_IMAGES = True # Download each rendered frame automatically (works best in firefox)
USE_L2_GRADIENT = True # Creates less edges but is still accurate (leads to faster renders)
SHOW_GRID = True # Show the grid in the background while rendering
SCALE_FACTOR = 4 # Scale factor for rendering, improves image download quality 
frame = multiprocessing.Value('i', 0)
height = multiprocessing.Value('i', 0, lock = False)
width = multiprocessing.Value('i', 0, lock = False)
frame_latex = 0

global imask
global image
def help():
    print('backend.py -f <source> -e <extension> -c <colour> -b -d -l -g --yes\n')
    print('\t-h\tGet help\n')
    print('-Options\n')
    print('\t-f <source>\tThe directory from which the frames are stored (e.g. frames)')
    print('\t-e <extension>\tThe extension of the frame files (e.g. png)')
    print('\t-c <colour>\tThe colour of the lines to be drawn (e.g. #2464b4)')
    print('\t-b\t\tReduce number of lines with bilateral filter for simpler renders')
    print('\t-d\t\tDownload rendered frames automatically')
    print('\t-l\t\tReduce number of lines with L2 gradient for quicker renders')
    print('\t-g\t\tHide the grid in the background of the graph\n')
    print('\t--yes\t\tAgree to EULA without input prompt')


def get_contours(filename, nudge = .33):
    global imask
    global image
    image = cv2.imread(filename)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    if BILATERAL_FILTER:
        median = max(10, min(245, np.median(gray)))
        lower = int(max(0, (1 - nudge) * median))
        upper = int(min(255, (1 + nudge) * median))
        filtered = cv2.bilateralFilter(gray, 5, 50, 50)
        edged = cv2.Canny(filtered, lower, upper, L2gradient = USE_L2_GRADIENT)
    else:
        edged = cv2.Canny(gray, 30, 200)

    with frame.get_lock():
        frame.value += 1
        height.value = max(height.value, image.shape[0])
        width.value = max(width.value, image.shape[1])
    print('\r--> Frame %d/%d' % (frame.value, len(os.listdir(FRAME_DIR))), end='')
    imask = cv2.bitwise_and(image, image, mask = edged)
    imask = imask[::-1]
    imask = cv2.cvtColor(imask, cv2.COLOR_BGR2RGB)
    return edged[::-1]


def get_trace(data):
    for i in range(len(data)):
        data[i][data[i] > 1] = 1
    bmp = potrace.Bitmap(data)
    path = bmp.trace(2, potrace.TURNPOLICY_MINORITY, 1.0, 1, .5)
    return path
#convert rgb to hex
def rgb2hex(r, g, b):
    r = int(r)
    g = int(g)
    b = int(b)
    return '#%02x%02x%02x' % (r, g, b)
#function to get closest non black color in image
def find_closest_color(y, x):
    col = [0, 0, 0]
    h, w  = y - 1, x - 1
    c = 0
    d = 1
    k = 1
    status = 1
    try:
        while c < 2:
            if imask[h, w][0] != 0 or imask[h, w][1] != 0 or imask[h, w][2] != 0:
                #print("found color!" + str(imask[h, w]))
                col[0] = imask[h, w][0]
                col[1] = imask[h, w][1]
                col[2] = imask[h, w][2]
                break
            if status == 1:
                w = w + d
                if w - x + 1 >= k:
                    status = 2
            elif status == 2:
                h = h + d
                if h - y + 1 >= k:
                    status = 3
            elif status == 3:
                w = w - d
                if -w + x - 1 >= k:
                    status = 4
            elif status == 4:
                h = h - d
                if -h + y - 1 >= k:
                    status = 1
                    k += 2
                    c += 1
    except Exception as e:
        print("exception! " + str(e))
        """
            if str(e) == 'index 240 is out of bounds for axis 0 with size 240':
            return find_closest_color(abs(y - 8), x)
        elif str(e) == 'index 426 is out of bounds for axis 1 with size 426':
            return find_closest_color(y, abs(x - 8))
        return find_closest_color(abs(y - 8), abs(x - 8))
        """
        
    #print(col)
    if len(col) == 0:
        return rgb2hex(image[h, w][0], image[h, w][1], image[h, w][2])
    return rgb2hex(col[0], col[1], col[2])

def get_latex(filename):
    latex = []
    hex_list = []
    path = get_trace(get_contours(filename))

    for curve in path.curves:
        segments = curve.segments
        start = curve.start_point
        for segment in segments:
            x0, y0 = start 
            if segment.is_corner:
                x1, y1 = segment.c
                x2, y2 = segment.end_point
                latex.append('((1-t)%f+t%f,(1-t)%f+t%f)' % (x0 * SCALE_FACTOR, x1 * SCALE_FACTOR, y0 * SCALE_FACTOR, y1 * SCALE_FACTOR))
                hex_list.append(find_closest_color(int(y0), int(x0)))
                latex.append('((1-t)%f+t%f,(1-t)%f+t%f)' % (x1 * SCALE_FACTOR, x2 * SCALE_FACTOR, y1 * SCALE_FACTOR, y2 * SCALE_FACTOR))
                hex_list.append(find_closest_color(int(y1), int(x1)))
            else:
                x1, y1 = segment.c1
                x2, y2 = segment.c2
                x3, y3 = segment.end_point
                latex.append('((1-t)((1-t)((1-t)%f+t%f)+t((1-t)%f+t%f))+t((1-t)((1-t)%f+t%f)+t((1-t)%f+t%f)),\
                (1-t)((1-t)((1-t)%f+t%f)+t((1-t)%f+t%f))+t((1-t)((1-t)%f+t%f)+t((1-t)%f+t%f)))' % \
                (x0 * SCALE_FACTOR, x1 * SCALE_FACTOR, x1 * SCALE_FACTOR, x2 * SCALE_FACTOR, x1 * SCALE_FACTOR, x2 * SCALE_FACTOR, x2 * SCALE_FACTOR, x3 * SCALE_FACTOR, y0 * SCALE_FACTOR, y1 * SCALE_FACTOR, y1 * SCALE_FACTOR, y2 * SCALE_FACTOR, y1 * SCALE_FACTOR, y2 * SCALE_FACTOR, y2 * SCALE_FACTOR, y3 * SCALE_FACTOR))
                hex_list.append(find_closest_color(int(y0), int(x0)))
            start = segment.end_point
    print(len(latex))
    return [latex, hex_list]


def get_expressions(frame):
    global BILATERAL_FILTER
    exprid = 0
    exprs = []
    result = get_latex(FRAME_DIR + '/frame%04d.%s' % (frame+1, FILE_EXT))
    if len(result[0]) >= 12000 and BILATERAL_FILTER == False:
        BILATERAL_FILTER = True
        return get_expressions(frame)
    elif len(result[0]) <= 3000 and BILATERAL_FILTER == True:
        BILATERAL_FILTER = False
        return get_expressions(frame)
    for i in range(len(result[0])):
        exprid += 1
        exprs.append({'id': 'expr-' + str(exprid), 'latex': result[0][i], 'color': result[1][i], 'secret': True})
    return exprs


@app.route('/')
def index():
    frame = int(request.args.get('frame'))
    if frame >= len(os.listdir(FRAME_DIR)):
        return {'result': None}

    return json.dumps({'result': frame_latex[frame] })


@app.route("/calculator")
def client():
    return render_template('index.html', api_key='dcb31709b452b1cf9dc26972add0fda6', # Development-only API_key. See https://www.desmos.com/api/v1.8/docs/index.html#document-api-keys
            height= SCALE_FACTOR * height.value, width= SCALE_FACTOR * width.value, total_frames=len(os.listdir(FRAME_DIR)), download_images=DOWNLOAD_IMAGES, show_grid=SHOW_GRID)


if __name__ == '__main__':

    try:
        opts, args = getopt.getopt(sys.argv[1:], "hf:e:c:bdlg", ['static', 'block=', 'maxpblock=', 'yes'])

    except getopt.GetoptError:
        print('Error: Invalid argument(s)\n')
        help()
        sys.exit(2)

    eula = ''

    try:
        for opt, arg in opts:
            if opt == '-h':
                help()
                sys.exit()
            elif opt == '-f':
                FRAME_DIR = arg
            elif opt == '-e':
                FILE_EXT = arg
            elif opt == '-c':
                COLOUR = arg
            elif opt == '-b':
                BILATERAL_FILTER = True
            elif opt == '-d':
                DOWNLOAD_IMAGES = True
            elif opt == '-l':
                USE_L2_GRADIENT = True
            elif opt == '-g':
                SHOW_GRID = False
            elif opt == '--yes':
                eula = 'y'
        frame_latex =  range(len(os.listdir(FRAME_DIR)))

    except TypeError:
        print('Error: Invalid argument(s)\n')
        help()
        sys.exit(2)

    with multiprocessing.Pool(processes = multiprocessing.cpu_count()) as pool:
        print('''  _____                                
 |  __ \                               
 | |  | | ___  ___ _ __ ___   ___  ___ 
 | |  | |/ _ \/ __| '_ ` _ \ / _ \/ __|
 | |__| |  __/\__ \ | | | | | (_) \__ \\
 |_____/ \___||___/_| |_| |_|\___/|___/
''')
        print('                   BEZIER RENDERER')
        print('Junferno 2021')
        print('https://github.com/kevinjycui/DesmosBezierRenderer')

        print('''
 = COPYRIGHT =
©Copyright Junferno 2021-2023. This program is licensed under the [GNU General Public License](https://github.com/kevinjycui/DesmosBezierRenderer/blob/master/LICENSE). Please provide proper credit to the author (Junferno) in any public media that uses this software. Desmos Bezier Renderer is in no way, shape, or form endorsed by or associated with Desmos, Inc.

 = EULA =
By using Desmos Bezier Renderer, you agree to comply to the [Desmos Terms of Service](https://www.desmos.com/terms). The Software and related documentation are provided “AS IS” and without any warranty of any kind. Desmos Bezier Renderer is not responsible for any User application or modification that constitutes a breach in terms. User acknowledges and agrees that the use of the Software is at the User's sole risk. The developer kindly asks Users to not use Desmos Bezier Renderer to enter into Desmos Math Art competitions, for the purpose of maintaining fairness and integrity.
''')

        while eula != 'y':
            eula = input('                                      Agree (y/n)? ')
            if eula == 'n':
                quit()

        print('-----------------------------')

        print('Processing %d frames... Please wait for processing to finish before running on frontend\n' % len(os.listdir(FRAME_DIR)))

        start = time()

        try:
            frame_latex = pool.map(get_expressions, frame_latex)
        except cv2.error as e:
            print('[ERROR] Unable to process one or more files. Remember image files should be named <DIRECTORY>/frame<INDEX>.<EXTENSION> where INDEX represents the frame number starting from 1 and DIRECTORY and EXTENSION are defined by command line arguments (e.g. frames/frame1.png). Please check if:\n\tThe files exist\n\tThe files are all valid image files\n\tThe name of the files given is correct as per command line arguments\n\tThe program has the necessary permissions to read the file.\n\nUse backend.py -h for further documentation\n')            

            print('-----------------------------')

            print('Full error traceback:\n')
            traceback.print_exc()
            sys.exit(2)

        print('\r--> Processing complete in %.1f seconds\n' % (time() - start))
        print('\t\t===========================================================================')
        print('\t\t|| GO CHECK OUT YOUR RENDER NOW AT:\t\t\t\t\t ||')
        print('\t\t||\t\t\thttp://127.0.0.1:5000/calculator\t\t ||')
        print('\t\t===========================================================================\n')
        print('=== SERVER LOG (Ignore if not dev) ===')

        # with open('cache.json', 'w+') as f:
        #     json.dump(frame_latex, f)

        app.run()
