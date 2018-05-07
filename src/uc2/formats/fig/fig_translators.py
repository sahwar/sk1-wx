# -*- coding: utf-8 -*-
#
#  Copyright (C) 2018 by Maxim S. Barabash
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import logging
from base64 import b64decode, b64encode
from copy import deepcopy

from uc2 import uc2const, sk2const, cms, libgeom
from uc2.formats.sk2 import sk2_model
from . import fig_const, fig_model, figlib
from .fig_colors import color_mix, FIG_COLORS
from .fig_const import (BLACK_COLOR, WHITE_COLOR, BLACK_FILL,
                        WHITE_FILL, NO_FILL, DEFAULT_COLOR)

LOG = logging.getLogger(__name__)

SK2_UNITS = {
    fig_const.METRIC: uc2const.UNIT_MM,
    fig_const.INCHES: uc2const.UNIT_IN
}

FIG_TO_SK2_JOIN = {
    fig_const.JOIN_MITER: sk2const.JOIN_MITER,
    fig_const.JOIN_ROUND: sk2const.JOIN_ROUND,
    fig_const.JOIN_BEVEL: sk2const.JOIN_BEVEL
}

FIG_TO_SK2_CAP = {
    fig_const.CAP_BUTT: sk2const.CAP_BUTT,
    fig_const.CAP_ROUND: sk2const.CAP_ROUND,
    fig_const.CAP_SQUARE: sk2const.CAP_SQUARE
}

#  FIXME: in line style the point size is not controlled
FIG_TO_SK2_LINE_STYLE = {
    fig_const.SOLID_LINE: [],
    fig_const.DASH_LINE: [2, 2],
    fig_const.DOTTED_LINE: [1, 1],
    fig_const.DASH_DOT_LINE: [2, 1, 1, 1],
    fig_const.DASH_2_DOTS_LINE: [2, 1, 1, 1, 1, 1],
    fig_const.DASH_3_DOTS_LINE: [2, 1, 1, 1, 1, 1, 1, 1],
}

FIG_TO_SK2_ARC = {
    fig_const.T_OPEN_ARC: sk2const.ARC_ARC,
    fig_const.T_PIE_WEDGE_ARC: sk2const.ARC_PIE_SLICE
}

class FIG_to_SK2_Translator(object):
    page = None
    layer = None
    trafo = None
    fig_doc = None
    sk2_doc = None
    fig_mt = None
    sk2_mt = None
    sk2_mtds = None
    fig_mtds = None
    id_map = None
    pallet = None
    thickness = None
    depth_layer = None

    def translate(self, fig_doc, sk2_doc):
        self.pallet = deepcopy(FIG_COLORS)
        self.fig_doc = fig_doc
        self.sk2_doc = sk2_doc
        self.fig_mt = fig_doc.model
        self.sk2_mt = sk2_doc.model
        self.fig_mtds = fig_doc.methods
        self.sk2_mtds = sk2_doc.methods
        lr = fig_doc.config.line_resolution or fig_const.LINE_RESOLUTION
        self.thickness = uc2const.in_to_pt / lr
        self.depth_layer = {}
        self.translate_trafo()
        self.translate_units()
        self.translate_metainfo()
        self.translate_page()
        self.translate_obj(self.fig_mt.childs, sk2_doc.config)
        self.apply_translate()

    def apply_translate(self):
        layer = self.sk2_mtds.get_layer(self.page)
        for depth in sorted(self.depth_layer, reverse=True):
            objects = self.depth_layer[depth]
            self.sk2_mtds.append_objects(objects, layer)

    def translate_trafo(self):
        trafo1 = self.fig_mtds.get_doc_trafo()
        width, height = self.fig_mtds.get_pages_size()
        trafo2 = [1.0, 0.0, 0.0, 1.0, -width / 2.0, height / 2.0]
        self.trafo = libgeom.multiply_trafo(trafo1, trafo2)

    def translate_units(self):
        self.sk2_mtds.set_doc_units(SK2_UNITS[self.fig_mtds.get_doc_units()])

    def translate_metainfo(self):
        metainfo = ['', '', '', '']
        metainfo[3] = b64encode(self.fig_mtds.get_doc_metainfo())
        self.sk2_mtds.set_doc_metainfo(metainfo)

    def translate_page(self):
        page_fmt = self.fig_mtds.get_pages_format()
        self.page = self.sk2_mtds.get_page()
        self.sk2_mtds.set_page_format(self.page, page_fmt)

    def translate_obj(self, childs, cfg):
        for child in childs:
            new_obj = None
            if child.cid == fig_model.OBJ_COLOR_DEF:
                self.translate_color(child, cfg)
            elif child.cid == fig_model.OBJ_COMPOUND:
                self.translate_obj(child.childs, cfg)
            elif child.cid == fig_model.OBJ_ELLIPSE:
                new_obj = self.translate_ellipse(child, cfg)
            elif child.cid == fig_model.OBJ_ARC:
                new_obj = self.translate_arc(child, cfg)
            elif child.cid == fig_model.OBJ_POLYLINE:
                new_obj = self.translate_polyline(child, cfg)
            if new_obj:
                self.get_depth_layer(child.depth).append(new_obj)

    def translate_arc(self, obj, cfg):
        cx = obj.center_x
        cy = obj.center_y
        r = libgeom.distance((cx, cy), (obj.x1, obj.y1))
        end_angle = libgeom.get_point_angle((obj.x1, obj.y1), (cx, cy))
        start_angle = libgeom.get_point_angle((obj.x3, obj.y3), (cx, cy))
        if not obj.direction:
            start_angle, end_angle = end_angle, start_angle
        circle_type = FIG_TO_SK2_ARC.get(obj.sub_type, sk2const.ARC_PIE_SLICE)
        props = dict(
            circle_type=circle_type,
            rect=[cx - r, cy - r, 2.0 * r, 2.0 * r],
            style=self.get_style(obj),
            angle1=start_angle,
            angle2=end_angle
        )
        new_obg = sk2_model.Circle(cfg, **props)
        new_obg.trafo = libgeom.multiply_trafo(new_obg.trafo, self.trafo)
        return new_obg

    def translate_ellipse(self, obj, cfg):
        cx = obj.center_x
        cy = obj.center_y
        rx = obj.radius_x
        ry = obj.radius_y
        props = dict(
            rect=[cx - rx, cy - ry, 2.0 * rx, 2.0 * ry],
            style=self.get_style(obj),
        )
        new_obg = sk2_model.Circle(cfg, **props)
        trafo_rotate = libgeom.trafo_rotate(-obj.angle, cx, cy)
        trafo = libgeom.multiply_trafo(new_obg.trafo, trafo_rotate)
        new_obg.trafo = libgeom.multiply_trafo(trafo, self.trafo)
        return new_obg

    def translate_color(self, obj, cfg):
        if obj.idx not in FIG_COLORS:
            rgb = cms.hexcolor_to_rgb(obj.hexcolor)
            color = [uc2const.COLOR_RGB, rgb, 1.0, obj.hexcolor]
            self.pallet[obj.idx] = color

    def translate_polyline(self, obj, cfg):
        tr = self.trafo
        style = self.get_style(obj)
        if obj.sub_type in (fig_const.T_ARC_BOX, fig_const.T_PIC_BOX):
            bbox = libgeom.bbox_for_points(obj.points)
            bbox_size = libgeom.bbox_size(bbox)
            rect = [bbox[0], bbox[1], bbox_size[0], bbox_size[1]]
            corners = sk2const.CORNERS
            if obj.sub_type == fig_const.T_ARC_BOX:
                try:
                    wide_side = max(bbox_size) * tr[0]
                    c = obj.radius * 2.0 * self.thickness / wide_side
                    corners = [c, c, c, c]
                except ZeroDivisionError:
                    pass
            else:
                pass  # TODO: implement fig_const.T_PIC_BOX
            props = dict(
                rect=rect, trafo=tr[:], style=style, corners=corners[:]
            )
            new_obj = sk2_model.Rectangle(cfg, **props)
        else:
            start_point, points = obj.points[0], obj.points[1:]
            end_marker = points and start_point == points[-1]
            paths = [[start_point, points, end_marker]]
            props = dict(paths=paths, trafo=tr[:], style=style)
            new_obj = sk2_model.Curve(cfg, **props)
        return new_obj

    def get_style(self, obj):
        fill = self.get_fill(obj.fill_color, obj.area_fill)
        stroke = self.get_stoke(obj)
        return [fill, stroke, [], []]

    def get_depth_layer(self, depth):
        return self.depth_layer.setdefault(depth, [])

    def get_fill(self, color, style):
        if style == NO_FILL:
            return []
        pallet = self.pallet
        rgb = pallet[color]
        coef = (BLACK_FILL - style) / BLACK_FILL
        if color == WHITE_COLOR:
            rgb = color_mix(rgb, pallet[BLACK_COLOR], coef)
        elif color in (BLACK_COLOR, DEFAULT_COLOR):
            rgb = color_mix(rgb, pallet[WHITE_COLOR], coef)
        else:
            if WHITE_FILL <= style < BLACK_FILL:
                rgb = color_mix(rgb, pallet[BLACK_COLOR], coef)
            elif BLACK_FILL < style <= BLACK_FILL * 2:
                coef = (style - BLACK_FILL) / BLACK_FILL
                rgb = color_mix(rgb, pallet[WHITE_COLOR], coef)
        if style > fig_const.BLACK_FILL * 2:
            # TODO: implement FILL_PATTERN
            fill = [sk2const.FILL_EVENODD, sk2const.FILL_SOLID, rgb]
        else:
            fill = [sk2const.FILL_EVENODD, sk2const.FILL_SOLID, rgb]
        return fill

    def get_stoke(self, obj):
        cap_style = sk2const.CAP_BUTT
        join_style = sk2const.JOIN_MITER
        if hasattr(obj, 'cap_style'):
            cap_style = FIG_TO_SK2_CAP.get(obj.cap_style, cap_style)
        if hasattr(obj, 'join_style'):
            join_style = FIG_TO_SK2_JOIN.get(obj.join_style, join_style)

        rule = sk2const.STROKE_MIDDLE
        width = obj.thickness * self.thickness
        color = deepcopy(self.pallet.get(obj.pen_color))
        dash = FIG_TO_SK2_LINE_STYLE.get(obj.line_style, [])[:]
        cap = cap_style
        join = join_style
        miter_limit = 10.433
        behind_flag = 0
        scalable_flag = 0
        markers = []  # TODO: implement translation arrows
        return [rule, width, color, dash, cap, join, miter_limit, behind_flag,
                scalable_flag, markers]


class SK2_to_FIG_Translator(object):
    dx = dy = page_dx = 0.0
    fig_doc = None
    sk2_doc = None
    fig_mt = None
    sk2_mt = None
    sk2_mtds = None
    fig_mtds = None

    def translate(self, sk2_doc, fig_doc):
        self.fig_doc = fig_doc
        self.sk2_doc = sk2_doc
        self.fig_mt = fig_doc.model
        self.sk2_mt = sk2_doc.model
        self.sk2_mtds = sk2_doc.methods
        self.fig_mtds = fig_doc.methods
        self.translate_metainfo()
        for item in self.sk2_mt.childs:
            if item.cid == sk2_model.PAGES:
                for page in item.childs:
                    self.translate_page(page)

    def translate_metainfo(self):
        fields = ["Author", "License", "Keywords", "Notes"]
        metainfo = deepcopy(self.sk2_mt.metainfo)
        metainfo[3] = b64decode(metainfo[3])
        metainfo = ['%s: %s' % i for i in zip(fields, metainfo) if i[1]]
        self.fig_mtds.set_doc_metainfo(metainfo)

    def translate_page(self, source_obj):
        mt = self.fig_mt
        mt.paper_size = source_obj.page_format[0]
        if source_obj.page_format[2] == uc2const.LANDSCAPE:
            mt.orientation = fig_const.LANDSCAPE
        else:
            mt.orientation = fig_const.PORTRAIT
