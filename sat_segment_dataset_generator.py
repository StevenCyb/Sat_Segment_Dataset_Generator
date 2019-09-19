import os
import cv2
import json
import math
import argparse
import requests
import numpy as np
import urllib.request
from copy import deepcopy

class SatSegmentDatasetGenerator:
    def __init__(self, here_app_id=None, here_app_code=None, config=None, output_path=None):
        if config is None:
            raise Exception("Please provide a configuration.")
        if here_app_id is None or here_app_code is None:
            raise Exception("Please provide your here api credentials.")
        if output_path is None:
            raise Exception("Please provide the ouput path.")
        self.here_app_id = here_app_id
        self.here_app_code = here_app_code
        self.config = config
        self.output_path = output_path
        self.here_map_tiles = []
        self.calculate_tiles()
        self.process_tiles()

    def calculate_tiles(self):
        lc = self.config["location_range"]
        print("Verify location configuration.")
        if(lc["top_left_location"]["latitude"] <= lc["bottom_right_location"]["latitude"]):
            raise Exception("The latitude of the starting point is not to the left of the end point.")
        if(lc["top_left_location"]["longitude"] >= lc["bottom_right_location"]["longitude"]):
            raise Exception("The longitude of the starting point is not to the left of the end point.")
        if(lc["zoom_range"]["min"] > lc["zoom_range"]["max"]):
            raise Exception("You flipped the zoom level in the wrong direction.")
        print("Calculate possible tiles -> ", end = '')
        for zoom in range(lc["zoom_range"]["max"], lc["zoom_range"]["min"] - 1, -1):
            top_left_tile_row = None
            top_left_tile_column = None
            bottom_right_tile_row = None
            bottom_right_tile_column = None
            top_left_tile_row, top_left_tile_column = self.calculate_heremap_coordinate(latitude=lc["top_left_location"]["latitude"], longitude=lc["top_left_location"]["longitude"], zoom=zoom)
            bottom_right_tile_row, bottom_right_tile_column = self.calculate_heremap_coordinate(latitude=lc["bottom_right_location"]["latitude"], longitude=lc["bottom_right_location"]["longitude"], zoom=zoom)
            if top_left_tile_column == bottom_right_tile_column and top_left_tile_row == bottom_right_tile_row: # Stop when top-left and bottom-right tiles are the same (max zoom reached)
                self.here_map_tiles.append([zoom, top_left_tile_row, top_left_tile_column])
                break
            else:
                for row in range(top_left_tile_row, bottom_right_tile_row + 1):
                    for column in range(top_left_tile_column, bottom_right_tile_column + 1):
                        self.here_map_tiles.append([zoom, row, column])
        print(str(len(self.here_map_tiles)) + " tiles to process.")

    def process_tiles(self):
        percentage_per_tile = 100 / len(self.here_map_tiles)
        counter = 0
        print("0.00%: Starting...", end = '\r')
        for here_map_tile_definition in self.here_map_tiles:
            filename = str(here_map_tile_definition[0]) + "_" + str(here_map_tile_definition[1]) + "_" + str(here_map_tile_definition[2])
            print(str(round(percentage_per_tile * counter, 2)) + "%: Download satellite image", end = '\r')
            satellite_tile = self.download_heramap_tile(here_map_tile_definition[0], here_map_tile_definition[1], here_map_tile_definition[2])
            print(str(round(percentage_per_tile * counter, 2)) + "%: Calculate geo-coordinates", end = '\r')
            # Calculate left-top corner
            left_top_latitude, left_top_longitude = self.heremap_to_geographical_coordinate(here_map_tile_definition[0], here_map_tile_definition[1], here_map_tile_definition[2])
            # Calculate right-top corner 
            right_top_latitude, right_top_longitude = self.heremap_to_geographical_coordinate(here_map_tile_definition[0], here_map_tile_definition[1], here_map_tile_definition[2] + 1)
            # Calculate left-bottom corner 
            left_bottom_latitude, left_bottom_longitude = self.heremap_to_geographical_coordinate(here_map_tile_definition[0], here_map_tile_definition[1] + 1, here_map_tile_definition[2])
            print(str(round(percentage_per_tile * counter, 2)) + "%: Download osm data          ", end = '\r')
            label_data = self.download_overpass_data(percentage=str(round(percentage_per_tile * counter, 2)), south_latitude=left_bottom_latitude, west_longitude=left_bottom_longitude, north_latitude=right_top_latitude, east_longitude=right_top_longitude)
            print(str(round(percentage_per_tile * counter, 2)) + "%: Draw mask                          ", end = '\r')
            mask = self.draw_mask(percentage=str(round(percentage_per_tile * counter, 2)), tile=satellite_tile, label_data=label_data, left_top=(left_top_latitude, left_top_longitude), right_top=(right_top_latitude, right_top_longitude), left_bottom=(left_bottom_latitude, left_bottom_longitude))
            print(str(round(percentage_per_tile * counter, 2)) + "%: Saving record                                ", end = '\r')
            cv2.imwrite(self.output_path + "/" + filename + ".jpg", satellite_tile)
            cv2.imwrite(self.output_path + "/" + filename + "_m.jpg", mask)
            print(str(round(percentage_per_tile * counter, 2)) + "%: OK           ", end = '\r')
            counter += 1
        print("100.00%: Finished                                   ", end = '\r')

    def calculate_heremap_coordinate(self, latitude=None, longitude=None, zoom=None):
        n = (2 ** zoom)
        latitude_rad = latitude * math.pi / 180
        column = n * ((longitude + 180) / 360)
        row = (n * (1 - (math.log( math.tan(latitude_rad) + (1 / math.cos(latitude_rad))) / math.pi))) / 2
        return int(row), int(column)

    def download_heramap_tile(self, zoom=None, row=None, column=None):
        return cv2.imdecode(np.asarray(bytearray(urllib.request.urlopen("https://1.aerial.maps.api.here.com/maptile/2.1/maptile/newest/satellite.day/" + str(zoom) + "/" + str(int(column)) + "/" + str(int(row)) + "/" + str(self.config["here_api"]["tile_size"]) + "/png" + "?app_id=" + self.here_app_id + "&app_code=" + self.here_app_code).read()), dtype='uint8'), cv2.IMREAD_COLOR)

    def heremap_to_geographical_coordinate(self, zoom=None, row=None, column=None):
        n = (2 ** zoom)
        latitude = (math.acos(1 / (0.5 * ((math.e ** (math.pi - (2.0 * row * math.pi)/n)) + (math.e ** ((2.0 * row * math.pi) / n - math.pi))))) * 180.0) / math.pi
        longitude = (360.0 * (column / n)) - 180.0
        return latitude, longitude

    def download_overpass_data(self, percentage="0.0.", south_latitude=None, west_longitude=None, north_latitude=None, east_longitude=None):
        counter = 1
        queries_count = str(len(self.config["categories"]))
        label_data = {"categories": [], "nodes": {}}
        for category in self.config["categories"]:
            dataset_category = {"draw_options":category["draw_options"],  "objects": []}
            print(percentage + "%: Download osm data [" + str(counter) + "/" + queries_count +"]", end = '\r')
            timeout_tries = 0
            last_response_code = 0
            while True:
                if timeout_tries > self.config["overpass_api"]["max_tries"]:
                    raise Exception("Overpass-Api error with code " + str(last_response_code))
                try:
                    response = requests.get("http://overpass-api.de/api/interpreter", timeout=(self.config["overpass_api"]["connection_establish_timeout"], self.config["overpass_api"]["response_timeout"]),params={"data": "[out:json];(" + category["overpass_api_query"].replace('{{bbox}}', str(south_latitude - category["expand_view"]) + ',' + str(west_longitude - category["expand_view"]) + ',' + str(north_latitude + category["expand_view"]) + ',' + str(east_longitude + category["expand_view"])) + ");out body;>;out skel qt;"})
                    if response.status_code != 200:
                        timeout_tries += 1
                        print(percentage + "%: Retry download " + str(timeout_tries) + "/" + str(self.config["overpass_api"]["max_tries"]) + " [" + str(counter) + "/" + queries_count +"]", end = '\r')
                        last_response_code = response.status_code
                        raise Exception("retry error")
                    else:
                        break
                except:
                    pass
            print(percentage + "%: Parse osm data [" + str(counter) + "/" + queries_count +"]  ", end = '\r')
            for element in response.json()["elements"]:
                if category["overpass_api_query"].startswith("node["):
                    dataset_category["objects"].append([element["id"]])
                if element["type"] == "way":
                    dataset_category["objects"].append(element["nodes"])
                elif element["type"] == "node": 
                    label_data["nodes"][element["id"]] = [float(element["lat"]), float(element["lon"])]
            label_data["categories"].append(dataset_category)
            counter += 1
        return label_data

    def draw_mask(self, percentage="0.0.", tile=None, label_data=None, left_top=None, right_top=None, left_bottom=None):
        mask = np.zeros((self.config["here_api"]["tile_size"], self.config["here_api"]["tile_size"], 3), dtype = "uint8")
        counter = 1
        category_count = str(len(label_data["categories"]))
        for category in label_data["categories"]:
            print(percentage + "%: Draw category on mask [" + str(counter) + "/" + category_count +"]", end = '\r')
            color = (category["draw_options"]["color"]["b"], category["draw_options"]["color"]["g"], category["draw_options"]["color"]["r"])
            if category["draw_options"]["type"] == "area":
                for obj in category["objects"]:
                    points = []
                    for id in obj:
                        node = label_data["nodes"][id]
                        points.append((node[0],node[1]))
                    points = self.geographical_coordinate_to_pixel(points, left_top=left_top, right_top=right_top, left_bottom=left_bottom)
                    cv2.drawContours(mask, [np.array(points, dtype=np.int32)], -1, color, -1)
            elif category["draw_options"]["type"] == "line":
                line_width = 1
                if "line_width" in category["draw_options"]:
                    line_width = category["draw_options"]["line_width"]
                for obj in category["objects"]:
                    points = []
                    for id in obj:
                        node = label_data["nodes"][id]
                        points.append((node[0],node[1]))
                    points = self.geographical_coordinate_to_pixel(points, left_top=left_top, right_top=right_top, left_bottom=left_bottom)
                    i = 0
                    while i < (len(points) - 1):
                        cv2.line(mask, (points[i][0], points[i][1]), (points[i + 1][0], points[i + 1][1]), color, line_width)
                        i += 1
            elif category["draw_options"]["type"] == "dot":
                circuit_radius = 3
                if "circuit_radius" in category["draw_options"]:
                    circuit_radius = category["draw_options"]["circuit_radius"]
                for obj in category["objects"]:
                    points = []
                    for id in obj:
                        node = label_data["nodes"][id]
                        points.append((node[0],node[1]))
                    points = self.geographical_coordinate_to_pixel(points, left_top=left_top, right_top=right_top, left_bottom=left_bottom)
                    for point in points:
                        cv2.circle(mask, (point[0], point[1]), circuit_radius, color, thickness=-1, lineType=8, shift=0)
            if "flood_fill" in category["draw_options"]:
                print(percentage + "%: Flood-Fill category on mask [" + str(counter) + "/" + category_count +"]", end = '\r')
                connected_components = 4
                flags = (connected_components | cv2.FLOODFILL_FIXED_RANGE | cv2.FLOODFILL_MASK_ONLY)
                height, width, _ = tile.shape
                flood_fill_image = deepcopy(tile)
                flood_fill_mask = np.zeros((height, width), dtype=np.uint8)
                ignore_border = 5
                for obj in category["objects"]:
                    points = []
                    for id in obj:
                        node = label_data["nodes"][id]
                        points.append((node[0],node[1]))
                    points = self.geographical_coordinate_to_pixel(points, left_top=left_top, right_top=right_top, left_bottom=left_bottom)
                    threshold = (category["draw_options"]["flood_fill"], category["draw_options"]["flood_fill"], category["draw_options"]["flood_fill"])
                    for point in points:
                        if point[0] >= ignore_border and point[1] >= ignore_border and point[0] <= (width - ignore_border) and point[1] <= (height - ignore_border) and flood_fill_mask[point[0],point[1]] == 0:
                            tmp = np.zeros((height + 2, width + 2), dtype=np.uint8)
                            cv2.floodFill(flood_fill_image, tmp, (point[0], point[1]), 0, category["draw_options"]["flood_fill"], threshold, flags)
                            flood_fill_mask = flood_fill_mask | tmp[1:-1, 1:-1]
                flood_fill_mask[flood_fill_mask!=0] = 255
                flood_fill_mask
                idx = (flood_fill_mask == 255)
                mask[idx] = color
            counter += 1
        return mask

    def geographical_coordinate_to_pixel(self, geographical_points=[], left_top=None, right_top=None, left_bottom=None):
        width_pp = self.config["here_api"]["tile_size"] / math.sqrt(((right_top[1] - left_top[1]) ** 2) + ((right_top[0] - left_top[0]) ** 2))
        height_pp = self.config["here_api"]["tile_size"] / math.sqrt(((left_top[1] - left_bottom[1]) ** 2) + ((left_top[0] - left_bottom[0]) ** 2)) 
        pixel_points = []
        for point in geographical_points:
            pixel_points.append([
                int(round(((point[1] + 180.0) - (left_top[1] + 180.0)) * width_pp)),
                int(round(((left_top[0] + 90.0) - (point[0] + 90.0)) * height_pp))
            ])
        return pixel_points

if __name__ == "__main__":
    # Define arguments with there default values
    ap = argparse.ArgumentParser()
    ap.add_argument("-app_id", "--here_app_id", required=True, help="Here-Api credentials.")
    ap.add_argument("-app_code", "--here_app_code", required=True, help="Here-Api credentials.")
    ap.add_argument("-output", "--output_path", required=True, help="Location to store the images.")
    ap.add_argument("-config", "--config_path", required=True, help="Location of the config file.")
    args = vars(ap.parse_args())

    # Verify the passed parameters
    if not os.path.isdir(args["output_path"]):
        os.mkdir(args["output_path"])
        print("Directory for dataset created on '" + args["output_path"] + "'.")
    if not os.path.isfile(args["config_path"]):
        raise Exception("Path to config is invalid.")

    # Load config as JSON
    print("Load configuration.")
    config = None
    with open(args["config_path"]) as json_file:
        config = json.load(json_file)
    # Create SatSegmentDatasetGenerator and do job
    satSegmentDatasetGenerator = SatSegmentDatasetGenerator(here_app_id=args["here_app_id"], here_app_code=args["here_app_code"], output_path=args["output_path"], config=config)
