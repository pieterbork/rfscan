from flask import render_template,request, make_response
from flask_socketio import emit
from time import time,strftime,sleep
from random import randrange
from rfscan import app,socketio
import thread
import datetime

import pdfkit
import os

from rfscan.core import database
from rfscan.core.utils import *
from rfscan.core.run_scans import scan_manager

#Required class to run PDFKit without x
class HeadlessPdfKit(pdfkit.PDFKit):
	def command(self, path=None):
		return ['xvfb-run', '--'] + super(HeadlessPdfKit, self).command(path)

@app.route('/', methods=["GET"])
def dash():
	jobs = database.get_records_from_table("Jobs")
	return render_template("dashboard.html", jobs=jobs)

@app.route('/to_pdf/<job>')
def to_pdf(job):
	job_id = database.get_job_id(job)
	wifi_records = database.get_records_from_table("Wifi", job_id)	
	zigbee_records = database.get_records_from_table("Zigbee", job_id)	
	bt_records = database.get_records_from_table("Bluetooth", job_id)	
	charts = {}

	#Build the tables/charts
	top_talkers = build_top_talkers_table(wifi_records)
	ssids = build_unique_ssids_table(wifi_records)
	charts['ssids_per_channel'] = build_chart_js("ssids_per_channel", wifi_records)
	charts['packets_per_channel'] = build_chart_js("packets_per_channel", wifi_records)

	#Make sure colors are consistent
	colors = generate_colors(charts['packets_per_channel']['channel_names'])
	charts['packets_per_channel']['colors'] = colors.values()
	charts['ssids_per_channel']['colors'] = [colors[ch] for ch in colors.keys() if ch in charts['ssids_per_channel']['channel_names']]
	
	rendered = render_template("results_pdf.html", 
				records={
					"Wifi":sorted(wifi_records, key=lambda x: x[6], reverse=True),
					"Wifi_fields": ["SSID", "MAC 1", "MAC 2", "MAC 3", "Frequency", "Count"],
					"Wifi_ssids": ssids,
					"top_talkers": top_talkers,
					"Zigbee":sorted(zigbee_records, key=lambda x: x[7], reverse=True), 
					"Zigbee_fields": ["Source", "Destination", "Ext Source", "Ext Dest", "Sec Source", "Sec Dest", "Count"],
					"Bluetooth":sorted(bt_records, key=lambda x: x[3], reverse=True),
					"Bluetooth_fields": ["Channel", "MAC", "Count"],
					"protocols": ["Wifi", "Zigbee", "Bluetooth"]
				}, 
				charts=charts,
				job=job)
	sleep(1)
	new_path = os.getcwd() + '/rfscan/static/'
	rendered = rendered.replace('/static/', new_path)
	opt = {'window-status': "done"}
	pdf = HeadlessPdfKit(rendered, 'string', options=opt).to_pdf(False)
#	pdf = pdfkit.from_string(rendered, False, options=opt)
	resp = make_response(pdf)
	resp.headers['Content-Type'] = 'application/pdf'
	resp.headers['Content-Disposition'] = 'inline; filename=output.pdf'
	return resp

@app.route('/scan', methods=["GET", "POST"])
def scan():
	if (request.method == "POST"):
		user_wifi_24_channels = []
		user_wifi_5_channels = []
		user_zigbee_channels = []
		user_bt_channels = []
		scan_time = 60
		set_scan_name = request.args.get('set_scan_name')
		try:
			scan_time = int(request.form['scan_time'])
			if scan_time < 0:
				scan_time = 0
		except ValueError:
			pass
		job_name = strftime("%Y-%m-%d_%H:%M:%S")
		if request.form['scan_name'] != "":
			job_name = str(request.form['scan_name'])	#TODO: sanitize this

		kwargs = {"socketio":socketio,
							"send_updates": True,
							"scan_time": scan_time,
							"scan_name": job_name}

		form_wifi_24_freq_list = request.form.getlist('wifi_select_24')
		form_wifi_24_freq_list.pop(0)		#to get rid of the placeholder that prevents flask errors
		for freq in form_wifi_24_freq_list:
			user_wifi_24_channels.append(freq)

		form_wifi_5_freq_list = request.form.getlist('wifi_select_5')
		form_wifi_5_freq_list.pop(0)		#to get rid of the placeholder that prevents flask errors
		for freq in form_wifi_5_freq_list:
			user_wifi_5_channels.append(freq)

		form_zigbee_freq_list = request.form.getlist('zigbee_select')
		form_zigbee_freq_list.pop(0)		#to get rid of the placeholder that prevents flask errors
		for freq in form_zigbee_freq_list:
			user_zigbee_channels.append(freq)

		form_bt_freq_list = request.form.getlist('bluetooth_select')
		form_bt_freq_list.pop(0)		#to get rid of the placeholder that prevents flask errors
		for freq in form_bt_freq_list:
			user_bt_channels.append(freq)

		if len(user_wifi_24_channels) > 0:
			kwargs['wifi_24_options'] = {"user_channels":user_wifi_24_channels}
		if len(user_wifi_5_channels) > 0:
			kwargs['wifi_5_options'] = {"user_channels":user_wifi_5_channels}
		if len(user_zigbee_channels) > 0:
			kwargs['zigbee_options'] = {"user_channels":user_zigbee_channels}
		if len(user_bt_channels) > 0:
			kwargs['bluetooth_options'] = {"user_channels":user_bt_channels}

		thread.start_new_thread(scan_manager, (), kwargs)
		return render_template("run_scan.html", 
					scan_time=kwargs['scan_time'],
					job=job_name)

	elif (request.method == "GET"):
		defaults = {
			"scan_name": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
			"scan_type": "new",
			"scan_time": 60,
			"Wifi2.4": [1, 6, 11],
			"Wifi5": [],
			"Bluetooth": [37],
			"Zigbee": [15, 20, 25, 26]
		}
		set_scan_name = request.args.get('set_scan_name')
		if(set_scan_name != None):
			defaults['scan_name'] = set_scan_name
			defaults['scan_type'] = "add"
		default_other_freqs = {
			"Zigbee": default_zigbee_freqs,
			"Bluetooth": default_bt_freqs
		}
		protocols = [("Wifi", "2.4", "wifi_select_24"), 
					 ("Wifi", "5", "wifi_select_5"), 
					 ("Bluetooth", "", "bluetooth_select"), 
					 ("Zigbee", "", "zigbee_select")]
		return render_template("show_scan.html", 
					default_bt_freqs=default_bt_freqs,
					all_wifi_freqs=all_wifi_freqs,
					default_other_freqs=default_other_freqs,
					defaults=defaults,
					protocols=protocols)

@app.route('/results/<job>')
def results(job):
	job_id = database.get_job_id(job)
	wifi_records = database.get_records_from_table("Wifi", job_id)	
	zigbee_records = database.get_records_from_table("Zigbee", job_id)	
	bt_records = database.get_records_from_table("Bluetooth", job_id)	
	charts = {}

	#Build the tables/charts
	top_talkers = build_top_talkers_table(wifi_records)
	ssids = build_unique_ssids_table(wifi_records)
	charts['ssids_per_channel'] = build_chart_js("ssids_per_channel", wifi_records)
	charts['packets_per_channel'] = build_chart_js("packets_per_channel", wifi_records)

	#Make sure colors are consistent
	colors = generate_colors(charts['packets_per_channel']['channel_names'])
	charts['packets_per_channel']['colors'] = colors.values()
	charts['ssids_per_channel']['colors'] = [colors[ch] for ch in colors.keys() if ch in charts['ssids_per_channel']['channel_names']]
	
	return render_template("results.html", 
				records={
					"Wifi":sorted(wifi_records, key=lambda x: x[6], reverse=True),
					"Wifi_fields": ["SSID", "MAC 1", "MAC 2", "MAC 3", "Frequency", "Count"],
					"Wifi_ssids": ssids,
					"top_talkers": top_talkers,
					"Zigbee":sorted(zigbee_records, key=lambda x: x[7], reverse=True), 
					"Zigbee_fields": ["Source", "Destination", "Ext Source", "Ext Dest", "Sec Source", "Sec Dest", "Count"],
					"Bluetooth":sorted(bt_records, key=lambda x: x[3], reverse=True),
					"Bluetooth_fields": ["Channel", "MAC", "Count"],
					"protocols": ["Wifi", "Zigbee", "Bluetooth"]
				}, 
				charts=charts,
				job=job)
