import dash
from dash import dcc, html, callback_context
import dash_bootstrap_components as dbc
from dash.dependencies import Input, Output, State
import sqlite3
import datetime
import os
import base64
import pandas as pd
import plotly.graph_objs as go
import logging

###################################################
# CONFIG & SETUP
###################################################

DB_PATH = '/home/mainhubs/SAPPHIRES.db'  # Adjust path as needed

EXTERNAL_STYLESHEETS = [
    dbc.themes.BOOTSTRAP,
    "https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&display=swap"
]

# Enhanced logging format includes log level
logging.basicConfig(
    filename='app.log',
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logging.debug("Starting application with extended modal workflow and error handling.")

###################################################
# DATABASE CONNECTION WITH ERROR HANDLING
###################################################

def get_db_connection():
    """
    Attempts to open a connection to the SQLite DB.
    Logs and re-raises on error.
    """
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        return conn
    except sqlite3.Error as e:
        logging.error(f"Database connection error: {e}")
        raise

def create_tables():
    """
    Create/upgrade tables. If there's an error, we log it.
    """
    create_tables_script = """
    CREATE TABLE IF NOT EXISTS Indoor (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        pm25 REAL,
        temperature REAL,
        humidity REAL
    );

    CREATE TABLE IF NOT EXISTS user_control (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        user_input TEXT
    );

    CREATE TABLE IF NOT EXISTS filter_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        filter_state TEXT CHECK (filter_state IN ('ON','OFF'))
    );

    CREATE TABLE IF NOT EXISTS Outdoor (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        pm25_value REAL,
        temperature REAL,
        humidity REAL,
        wifi_strength REAL
    );

    CREATE TABLE IF NOT EXISTS processed_events (
        processed_id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        processed_timestamp TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS reminders (
        reminder_id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL,
        reminder_time TEXT NOT NULL,
        reminder_type TEXT NOT NULL
    );
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.executescript(create_tables_script)
        conn.commit()
        logging.info("Tables created or verified successfully.")
    except sqlite3.Error as e:
        logging.error(f"Error creating tables: {e}")
    except Exception as ex:
        logging.exception(f"Unexpected error creating tables: {ex}")
    finally:
        if conn:
            conn.close()

# Initialize / upgrade tables on startup
create_tables()

###################################################
# HELPER FUNCTIONS (WITH ERROR HANDLING)
###################################################

def encode_image(image_path):
    """
    Returns a base64-encoded string of the image at image_path.
    Logs a warning if file does not exist or can't be read.
    """
    if not os.path.exists(image_path):
        logging.warning(f"Image file not found: {image_path}")
        return ""
    try:
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception as e:
        logging.error(f"Error encoding image {image_path}: {e}")
        return ""

def get_aqi_emoji(aqi):
    """
    Simplified placeholder for example.
    Could add more advanced logic to map AQI to emoticons.
    """
    return "😷"

def get_gauge_color(aqi):
    if aqi < 50:
        return "green"
    elif aqi < 100:
        return "yellow"
    elif aqi < 150:
        return "orange"
    else:
        return "red"

def get_fallback_gauge():
    """
    Returns a simple fallback gauge figure to display when an error occurs
    or data is unavailable.
    """
    fig = go.Figure()
    fig.add_annotation(text="Data Unavailable", x=0.5, y=0.5, showarrow=False, font=dict(size=16))
    fig.update_layout(
        height=300,
        margin=dict(t=0, b=50, l=50, r=50),
        paper_bgcolor="lightgray"
    )
    return fig

def get_last_filter_state():
    """
    Returns (id, filter_state) of the most recent entry in filter_state.
    Returns (None, 'OFF') if not found or if there's an error.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, filter_state FROM filter_state ORDER BY id DESC LIMIT 1')
        result = cursor.fetchone()
        if not result:
            logging.info("No rows found in filter_state table; returning OFF as default.")
            return (None, "OFF")
        return result
    except sqlite3.Error as e:
        logging.error(f"Error fetching last_filter_state: {e}")
        return (None, "OFF")
    except Exception as ex:
        logging.exception(f"Unexpected error in get_last_filter_state: {ex}")
        return (None, "OFF")
    finally:
        if conn:
            conn.close()

def get_latest_user_control():
    """
    Returns the most recent user_input from user_control (e.g., 'ON' or 'OFF').
    Returns 'OFF' if not found or error.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_input FROM user_control ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row is None:
            logging.info("No user_control rows found; defaulting to OFF.")
            return "OFF"
        return row[0]
    except sqlite3.Error as e:
        logging.error(f"Error in get_latest_user_control: {e}")
        return "OFF"
    except Exception as ex:
        logging.exception(f"Unexpected error in get_latest_user_control: {ex}")
        return "OFF"
    finally:
        if conn:
            conn.close()

def is_event_processed(event_id):
    """
    Checks if the event_id is recorded in processed_events.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT event_id FROM processed_events WHERE event_id=?',(event_id,))
        result = cursor.fetchone()
        return (result is not None)
    except sqlite3.Error as e:
        logging.error(f"Error checking processed_events for event {event_id}: {e}")
        return False
    except Exception as ex:
        logging.exception(f"Unexpected error in is_event_processed: {ex}")
        return False
    finally:
        if conn:
            conn.close()

def record_event_as_processed(event_id, action):
    """
    Inserts a row into processed_events with the user action or event status
    (e.g., 'ON', 'OFF', 'REMIND_20', 'SHOWING_MODAL', etc.).
    """
    conn = None
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO processed_events (event_id, action, processed_timestamp) VALUES (?,?,?)',
            (event_id, action, timestamp)
        )
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error recording processed event {event_id}, action={action}: {e}")
    except Exception as ex:
        logging.exception(f"Unexpected error in record_event_as_processed: {ex}")
    finally:
        if conn:
            conn.close()

def add_reminder(event_id, delay_minutes, reminder_type):
    """
    Inserts a future reminder for the given event_id.
    If there's an error, logs it, no exception raised.
    """
    conn = None
    try:
        reminder_time = (datetime.datetime.now() + datetime.timedelta(minutes=delay_minutes)).strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO reminders (event_id, reminder_time, reminder_type) VALUES (?,?,?)',
            (event_id, reminder_time, reminder_type)
        )
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error adding reminder for event {event_id}: {e}")
    except Exception as ex:
        logging.exception(f"Unexpected error in add_reminder: {ex}")
    finally:
        if conn:
            conn.close()

def get_due_reminder():
    """
    Return (event_id, reminder_id) if a reminder_time <= now is found.
    If none found or on error, returns (None, None).
    """
    conn = None
    try:
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT event_id, reminder_id FROM reminders WHERE reminder_time <= ?', (current_time,))
        result = cursor.fetchone()
        return result if result else (None, None)
    except sqlite3.Error as e:
        logging.error(f"Error in get_due_reminder: {e}")
        return (None, None)
    except Exception as ex:
        logging.exception(f"Unexpected error in get_due_reminder: {ex}")
        return (None, None)
    finally:
        if conn:
            conn.close()

def remove_reminder(reminder_id):
    """
    Deletes the reminder row by ID once triggered or no longer needed.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM reminders WHERE reminder_id=?', (reminder_id,))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error removing reminder {reminder_id}: {e}")
    except Exception as ex:
        logging.exception(f"Unexpected error in remove_reminder: {ex}")
    finally:
        if conn:
            conn.close()

def update_user_control_decision(state):
    """
    Inserts a new row into user_control with 'ON' or 'OFF'.
    """
    conn = None
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO user_control (timestamp, user_input) VALUES (?,?)', (timestamp, state))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error updating user_control to {state}: {e}")
    except Exception as ex:
        logging.exception(f"Unexpected error in update_user_control_decision: {ex}")
    finally:
        if conn:
            conn.close()

###################################################
# LAYOUTS
###################################################

def dashboard_layout():
    return dbc.Container([
        # Gauges
        dcc.Graph(id='indoor-gauge'),
        dcc.Graph(id='outdoor-gauge'),
        html.Div(id='indoor-temp-display'),
        html.Div(id='outdoor-temp-display'),

        # Interval for periodic updates
        dcc.Interval(id='interval-component', interval=10*1000, n_intervals=0),

        # Persistent Stores
        dcc.Store(id='on-alert-shown', data=False, storage_type='local'),
        dcc.Store(id='modal-open-state', data=False, storage_type='local'),
        dcc.Store(id='disclaimer-modal-open', data=False, storage_type='local'),
        dcc.Store(id='caution-modal-open', data=False, storage_type='local'),

        # Main Air Quality Degradation Modal
        dbc.Modal(
            [
                dbc.ModalHeader(
                    html.H4("AIR QUALITY DEGRADATION DETECTED", style={'color':'red'}),
                    className="bg-light"
                ),
                dbc.ModalBody(
                    "The air quality in your home has degraded to harmful levels. "
                    "Would you like to enable the fan and filter the air?",
                    style={'backgroundColor':'#f0f0f0','color':'black'}
                ),
                dbc.ModalFooter([
                    dbc.Button("Yes", id="enable-fan-filterstate", color="success", className="me-2", style={"width":"170px"}),
                    dbc.Button("No, keep fan off", id="keep-fan-off-filterstate", color="danger", className="me-2", style={"width":"170px"}),
                    dbc.Button("Remind me in 20 minutes", id="remind-me-filterstate", color="secondary"),
                    dbc.Button("Remind me in an hour", id="remind-me-hour-filterstate", color="secondary")
                ])
            ],
            id="modal-air-quality-filterstate",
            is_open=False,
            size="lg",
            centered=True,
            backdrop='static',
            keyboard=False
        ),

        # Disclaimer Modal
        dbc.Modal(
            [
                dbc.ModalHeader(html.H4("DISCLAIMER", style={'color':'red'}), className="bg-light"),
                dbc.ModalBody(
                    "Proceeding without enabling the fan may result in harmful or hazardous conditions. "
                    "Are you sure you want to keep the fan disabled?",
                    style={'backgroundColor':'#f0f0f0','color':'black'}
                ),
                dbc.ModalFooter([
                    dbc.Button("Yes (not recommended)", id="disclaimer-yes", color="danger", className="me-2", style={"width":"180px"}),
                    dbc.Button("No (Enable Fan)", id="disclaimer-no", color="secondary", style={"width":"180px"})
                ])
            ],
            id="modal-disclaimer",
            is_open=False,
            size="lg",
            centered=True,
            backdrop='static',
            keyboard=False
        ),

        # Caution Modal
        dbc.Modal(
            [
                dbc.ModalHeader(html.H4("CAUTION", style={'color':'red'}), className="bg-light"),
                dbc.ModalBody(
                    "The fan is currently turned off. Please note that you may be exposed to poor air quality. "
                    "To enable the fan later, please come back to this dashboard and select the Enable Fan option "
                    "when prompted.",
                    style={'backgroundColor':'#f0f0f0','color':'black'}
                ),
                dbc.ModalFooter([
                    dbc.Button("Close", id="caution-close", color="secondary", style={"width":"100px"})
                ])
            ],
            id="modal-caution",
            is_open=False,
            size="lg",
            centered=True,
            backdrop='static',
            keyboard=False
        ),

        # Fan Status Box (bottom-right corner)
        html.Div(
            id="fan-status-box",
            style={
                "position": "absolute",
                "bottom": "10px",
                "right": "10px",
                "padding": "8px 12px",
                "border": "2px solid #aaa",
                "borderRadius": "6px",
                "backgroundColor": "#f9f9f9",
                "fontWeight": "bold"
            }
        ),

        html.Div(id='relay-status', className="text-center mt-4")
    ], fluid=True, className="p-4")

def historical_conditions_layout():
    """
    Constructs the historical conditions layout, showing line charts of indoor/outdoor PM readings.
    Includes basic error handling and defaults if data is unavailable.
    """
    conn = None
    try:
        conn = get_db_connection()
        # Limit to last 500 readings
        indoor_data = pd.read_sql("SELECT timestamp, pm25 FROM Indoor ORDER BY timestamp DESC LIMIT 500;", conn)
        outdoor_data = pd.read_sql("SELECT timestamp, pm25_value FROM Outdoor ORDER BY timestamp DESC LIMIT 500;", conn)
    except Exception as e:
        logging.exception(f"Error retrieving historical data: {e}")
        indoor_data = pd.DataFrame(columns=["timestamp", "pm25"])
        outdoor_data = pd.DataFrame(columns=["timestamp", "pm25_value"])
    finally:
        if conn:
            conn.close()

    # Convert timestamps and handle empty data gracefully
    if not indoor_data.empty:
        indoor_data['timestamp'] = pd.to_datetime(indoor_data['timestamp'])
    else:
        logging.warning("No indoor data found for historical layout.")
    if not outdoor_data.empty:
        outdoor_data['timestamp'] = pd.to_datetime(outdoor_data['timestamp'])
    else:
        logging.warning("No outdoor data found for historical layout.")

    fig = go.Figure()
    if not indoor_data.empty:
        fig.add_trace(go.Scatter(
            x=indoor_data['timestamp'],
            y=indoor_data['pm25'],
            mode='lines',
            name='Indoor PM',
            line=dict(color='red', width=2, shape='spline'),
            hoverinfo='x+y',
        ))
    if not outdoor_data.empty:
        fig.add_trace(go.Scatter(
            x=outdoor_data['timestamp'],
            y=outdoor_data['pm25_value'],
            mode='lines',
            name='Outdoor PM',
            line=dict(color='blue', width=2, shape='spline'),
            hoverinfo='x+y',
        ))

    # Configure layout
    fig.update_layout(
        xaxis=dict(
            title="Time",
            showgrid=True,
            gridcolor='lightgrey',
            titlefont=dict(size=14, family="Roboto, sans-serif"),
            tickfont=dict(size=12)
        ),
        yaxis=dict(
            title="AQI",
            showgrid=True,
            gridcolor='lightgrey',
            titlefont=dict(size=14, family="Roboto, sans-serif"),
            tickfont=dict(size=12)
        ),
        template="plotly_white",
        legend=dict(
            orientation="h",
            x=0.5,
            y=-.05,
            xanchor="center",
            font=dict(size=12, family="Roboto, sans-serif")
        ),
        height=300,
        margin=dict(l=40, r=40, t=40, b=40)
    )

    return dbc.Container([
        dbc.Row(dbc.Col(html.H1("Historical Conditions", className="text-center mb-4"))),
        dbc.Row(dbc.Col(dcc.Graph(figure=fig, config={"displayModeBar": False}))),
    ], fluid=True, className="p-4")

###################################################
# INITIALIZE DASH APP
###################################################

app = dash.Dash(
    __name__,
    external_stylesheets=EXTERNAL_STYLESHEETS,
    suppress_callback_exceptions=True,
    meta_tags=[{"name":"viewport","content":"width=device-width,initial-scale=1"}]
)

app.layout = html.Div(
    style={"overflow":"hidden","height":"100vh"},
    children=[
        dcc.Location(id='url', refresh=False),
        html.Div(id='page-content', style={"outline":"none"})
    ]
)

# Custom index string
app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>Dashboard</title>
        {%favicon%}
        {%css%}
        <style>
            body {
                margin:0;
                overflow:hidden;
                font-family:"Roboto",sans-serif;
            }
        </style>
        <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
    </head>
    <body>
        {%app_entry%}
        <script>
            let startX=0,endX=0;
            document.addEventListener('touchstart',function(e){startX=e.changedTouches[0].screenX;},false);
            document.addEventListener('touchend',function(e){endX=e.changedTouches[0].screenX;handleSwipe();},false);
            function handleSwipe(){
                const deltaX=endX-startX;
                if(deltaX>50){
                    window.history.pushState({},"","/");
                    window.dispatchEvent(new PopStateEvent('popstate'));
                }else if(deltaX<-50){
                    window.history.pushState({},"","/historical");
                    window.dispatchEvent(new PopStateEvent('popstate'));
                }
            }
        </script>
        {%config%}
        {%scripts%}
        {%renderer%}
    </body>
</html>
'''

###################################################
# PAGE ROUTING
###################################################
@app.callback(
    Output('page-content','children'),
    Input('url','pathname')
)
def display_page(pathname):
    if pathname == '/':
        return dashboard_layout()
    elif pathname == '/historical':
        return historical_conditions_layout()
    else:
        return html.Div("Page not found", className="text-center")

###################################################
# DASHBOARD UPDATE CALLBACK
###################################################
@app.callback(
    [
        Output('indoor-gauge','figure'),
        Output('outdoor-gauge','figure'),
        Output('indoor-temp-display','children'),
        Output('outdoor-temp-display','children')
    ],
    [Input('interval-component','n_intervals')]
)
def update_dashboard(n):
    """
    Periodically fetches the latest indoor/outdoor data from the database,
    updates:
        - Indoor/Outdoor AQI gauges
        - Indoor/Outdoor temperature displays

    If an error occurs, logs it and provides fallback figures / text.
    """
    try:
        conn = get_db_connection()
    except Exception as e:
        logging.exception(f"update_dashboard: DB connection failed: {e}")
        # Return fallback
        return get_fallback_gauge(), get_fallback_gauge(), "N/A", "N/A"

    if conn is None:
        logging.error("update_dashboard: Could not get DB connection (conn is None).")
        return get_fallback_gauge(), get_fallback_gauge(), "N/A", "N/A"

    try:
        # Default fallback values
        indoor_aqi = 0
        outdoor_aqi = 0
        indoor_temp_text = "N/A"
        outdoor_temp_text = "N/A"
        indoor_arrow = "⬇️"
        outdoor_arrow = "⬇️"
        indoor_arrow_color = "green"
        outdoor_arrow_color = "green"
        indoor_delta_text = "0"
        outdoor_delta_text = "0"

        # Query data
        indoor_pm = pd.read_sql("SELECT pm25 FROM Indoor ORDER BY timestamp DESC LIMIT 60;", conn)
        outdoor_pm = pd.read_sql("SELECT pm25_value FROM Outdoor ORDER BY timestamp DESC LIMIT 60;", conn)
        indoor_temp_df = pd.read_sql("SELECT temperature FROM Indoor ORDER BY timestamp DESC LIMIT 1;", conn)
        outdoor_temp_df = pd.read_sql("SELECT temperature FROM Outdoor ORDER BY timestamp DESC LIMIT 1;", conn)

        # Close DB connection
        conn.close()

        # Indoor AQI
        if not indoor_pm.empty:
            indoor_aqi = round(indoor_pm['pm25'].iloc[0])
            if len(indoor_pm) > 30:
                indoor_delta = indoor_aqi - round(indoor_pm['pm25'].iloc[30:].mean())
            else:
                indoor_delta = 0
            indoor_delta_text = f"+{indoor_delta}" if indoor_delta > 0 else str(indoor_delta)
            indoor_arrow = "⬆️" if indoor_delta > 0 else "⬇️"
            indoor_arrow_color = "red" if indoor_delta > 0 else "green"
        else:
            logging.warning("update_dashboard: No indoor_pm data found.")

        # Outdoor AQI
        if not outdoor_pm.empty:
            outdoor_aqi = round(outdoor_pm['pm25_value'].iloc[0])
            if len(outdoor_pm) > 30:
                outdoor_delta = outdoor_aqi - round(outdoor_pm['pm25_value'].iloc[30:].mean())
            else:
                outdoor_delta = 0
            outdoor_delta_text = f"+{outdoor_delta}" if outdoor_delta > 0 else str(outdoor_delta)
            outdoor_arrow = "⬆️" if outdoor_delta > 0 else "⬇️"
            outdoor_arrow_color = "red" if outdoor_delta > 0 else "green"
        else:
            logging.warning("update_dashboard: No outdoor_pm data found.")

        # Indoor temperature
        if not indoor_temp_df.empty:
            indoor_temp_value = round(indoor_temp_df['temperature'].iloc[0], 1)
            indoor_temp_text = f"{indoor_temp_value} °F"
        else:
            logging.warning("update_dashboard: No indoor_temp_df data found.")

        # Outdoor temperature
        if not outdoor_temp_df.empty:
            outdoor_temp_value = round(outdoor_temp_df['temperature'].iloc[0], 1)
            outdoor_temp_text = f"{outdoor_temp_value} °F"
        else:
            logging.warning("update_dashboard: No outdoor_temp_df data found.")

        # Helper function to position text
        def get_x_positions(aqi, delta_text, base_x=0.45, char_spacing=0.02):
            aqi_length = len(str(aqi))
            delta_length = len(delta_text)
            adjusted_base_x = base_x - (aqi_length * char_spacing)

            aqi_x = adjusted_base_x
            arrow_x = aqi_x + (aqi_length * char_spacing * 1.5)
            delta_x = aqi_x + (aqi_length * char_spacing * 2)
            return aqi_x, arrow_x, delta_x

        # Build Indoor Gauge
        aqi_x, arrow_x, delta_x = get_x_positions(indoor_aqi, indoor_delta_text)
        indoor_gauge = go.Figure(go.Indicator(
            mode="gauge",
            value=indoor_aqi,
            gauge={
                'axis': {'range': [0, 150]},
                'bar': {'color': get_gauge_color(indoor_aqi)},
                'bgcolor': "lightgray",
                'bordercolor': "black",
            },
            domain={'x': [0, 1], 'y': [0, 1]}
        ))
        indoor_gauge.update_layout(height=300, margin=dict(t=0, b=50, l=50, r=50))
        indoor_gauge.add_annotation(
            x=aqi_x, y=0.25,
            text=f"<b>AQI:{indoor_aqi}</b>",
            showarrow=False,
            font=dict(size=30, color="black"),
            xanchor="center", yanchor="bottom"
        )
        indoor_gauge.add_annotation(
            x=arrow_x, y=0.24,
            text=indoor_arrow,
            font=dict(size=30, color=indoor_arrow_color),
            showarrow=False
        )
        indoor_gauge.add_annotation(
            x=delta_x, y=0.28,
            text=indoor_delta_text,
            font=dict(size=20, color=indoor_arrow_color),
            showarrow=False
        )

        # Build Outdoor Gauge
        aqi_x, arrow_x, delta_x = get_x_positions(outdoor_aqi, outdoor_delta_text)
        outdoor_gauge = go.Figure(go.Indicator(
            mode="gauge",
            value=outdoor_aqi,
            gauge={
                'axis': {'range': [0, 150]},
                'bar': {'color': get_gauge_color(outdoor_aqi)},
                'bgcolor': "lightgray",
                'bordercolor': "black",
            },
            domain={'x': [0, 1], 'y': [0, 1]}
        ))
        outdoor_gauge.update_layout(height=300, margin=dict(t=0, b=50, l=50, r=50))
        outdoor_gauge.add_annotation(
            x=aqi_x, y=0.25,
            text=f"<b>AQI:{outdoor_aqi}</b>",
            showarrow=False,
            font=dict(size=30, color="black"),
            xanchor="center", yanchor="bottom"
        )
        outdoor_gauge.add_annotation(
            x=arrow_x, y=0.24,
            text=outdoor_arrow,
            font=dict(size=30, color=outdoor_arrow_color),
            showarrow=False
        )
        outdoor_gauge.add_annotation(
            x=delta_x, y=0.28,
            text=outdoor_delta_text,
            font=dict(size=20, color=outdoor_arrow_color),
            showarrow=False
        )

        # Return figures and text
        return indoor_gauge, outdoor_gauge, indoor_temp_text, outdoor_temp_text

    except Exception as ex:
        logging.exception(f"Error in update_dashboard callback: {ex}")
        # Provide fallback
        return get_fallback_gauge(), get_fallback_gauge(), "N/A", "N/A"

###################################################
# FAN STATUS UPDATE
###################################################
@app.callback(
    Output("fan-status-box", "children"),
    [Input("interval-component", "n_intervals")]
)
def update_fan_status(n):
    """
    Checks if the latest filter_state == 'ON' AND latest user_control == 'ON'.
    If both are ON, display 'Fan is currently ON' (green).
    Otherwise, 'Fan is currently OFF' (red).
    """
    try:
        _, last_filter_state = get_last_filter_state()
        last_user_control = get_latest_user_control()

        if last_filter_state == "ON" and last_user_control == "ON":
            return html.Span("Fan is currently ON", style={"color": "green"})
        else:
            return html.Span("Fan is currently OFF", style={"color": "red"})
    except Exception as ex:
        logging.exception(f"Error in update_fan_status: {ex}")
        # Fallback text
        return html.Span("Fan status unknown", style={"color": "gray"})

###################################################
# MODAL HANDLING CALLBACK
###################################################
@app.callback(
    [
        Output("modal-air-quality-filterstate","is_open"),
        Output("on-alert-shown","data"),
        Output("relay-status","children"),
        Output("modal-disclaimer","is_open"),
        Output("modal-caution","is_open"),
        Output("modal-open-state","data"),
        Output("disclaimer-modal-open","data"),
        Output("caution-modal-open","data")
    ],
    [
        Input("interval-component","n_intervals"),
        Input("enable-fan-filterstate","n_clicks"),
        Input("keep-fan-off-filterstate","n_clicks"),
        Input("remind-me-filterstate","n_clicks"),
        Input("remind-me-hour-filterstate","n_clicks"),
        Input("disclaimer-yes","n_clicks"),
        Input("disclaimer-no","n_clicks"),
        Input("caution-close","n_clicks")
    ],
    [
        State("on-alert-shown","data"),
        State("modal-open-state","data"),
        State("disclaimer-modal-open","data"),
        State("caution-modal-open","data")
    ]
)
def handle_filter_state_event(n_intervals,
                              enable_clicks,
                              keep_off_clicks,
                              remind_me_clicks,
                              remind_me_hour_clicks,
                              disclaimer_yes_clicks,
                              disclaimer_no_clicks,
                              caution_close_clicks,
                              alert_shown,
                              modal_open_state,
                              disclaimer_open_state,
                              caution_open_state):
    """
    Handles logic for showing modals, disclaimers, reminders,
    and user choices (Yes/No/Remind).
    """
    try:
        triggered_id = callback_context.triggered[0]["prop_id"].split(".")[0]

        # Start from stored states
        modal_open = modal_open_state
        disclaimer_open = disclaimer_open_state
        caution_open = caution_open_state
        status_message = "Monitoring filter state..."
        updated_alert_shown = alert_shown

        last_event_id, last_state = get_last_filter_state()
        due_reminder_event_id, reminder_id = get_due_reminder()

        # Check if a reminder is due
        if due_reminder_event_id and due_reminder_event_id == last_event_id and last_state == "ON":
            modal_open = True
            disclaimer_open = False
            caution_open = False
            updated_alert_shown = True
            remove_reminder(reminder_id)
            status_message = "Reminder due. Showing modal."

        # If interval triggered, filter_state=ON, and event not processed
        elif triggered_id == "interval-component" and last_state == "ON" and last_event_id:
            if not is_event_processed(last_event_id):
                modal_open = True
                disclaimer_open = False
                caution_open = False
                updated_alert_shown = True
                status_message = f"Filter ON detected. Event {last_event_id}. User attention required."
                record_event_as_processed(last_event_id, "SHOWING_MODAL")

        # Handle user clicks
        if triggered_id == "enable-fan-filterstate":
            update_user_control_decision("ON")
            modal_open = False
            disclaimer_open = False
            caution_open = False
            status_message = "Fan enabled by user choice."

            if last_event_id:
                record_event_as_processed(last_event_id, "ON")

        elif triggered_id == "keep-fan-off-filterstate":
            modal_open = False
            disclaimer_open = True
            caution_open = False
            status_message = "User chose to keep fan off, showing disclaimer."

        elif triggered_id == "remind-me-filterstate":
            modal_open = False
            disclaimer_open = False
            caution_open = False
            if last_event_id:
                add_reminder(last_event_id, 20, "20 minutes")
                record_event_as_processed(last_event_id, "REMIND_20")
            status_message = "Reminder set for 20 minutes."

        elif triggered_id == "remind-me-hour-filterstate":
            modal_open = False
            disclaimer_open = False
            caution_open = False
            if last_event_id:
                add_reminder(last_event_id, 60, "1 hour")
                record_event_as_processed(last_event_id, "REMIND_60")
            status_message = "Reminder set for 1 hour."

        elif triggered_id == "disclaimer-yes":
            modal_open = False
            disclaimer_open = False
            caution_open = True
            status_message = "User insisted on keeping fan off, showing caution."

            update_user_control_decision("OFF")
            if last_event_id:
                record_event_as_processed(last_event_id, "OFF")

        elif triggered_id == "disclaimer-no":
            update_user_control_decision("ON")
            modal_open = False
            disclaimer_open = False
            caution_open = False
            status_message = "User changed mind at disclaimer, fan enabled."

            if last_event_id:
                record_event_as_processed(last_event_id, "ON")

        elif triggered_id == "caution-close":
            modal_open = False
            disclaimer_open = False
            caution_open = False
            status_message = "Caution modal closed, user aware fan is off."

        return (
            modal_open,
            updated_alert_shown,
            status_message,
            disclaimer_open,
            caution_open,
            modal_open,
            disclaimer_open,
            caution_open
        )
    except Exception as ex:
        logging.exception(f"Error in handle_filter_state_event callback: {ex}")
        # If something goes wrong, just return the states unchanged
        return (
            modal_open_state,
            alert_shown,
            "Error encountered in callback. Check logs.",
            disclaimer_open_state,
            caution_open_state,
            modal_open_state,
            disclaimer_open_state,
            caution_open_state
        )

###################################################
# RUN
###################################################
if __name__ == '__main__':
    app.run_server(debug=False)
