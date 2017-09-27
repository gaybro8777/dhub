#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import csv
import json
import os
from mldata.element import Element
from mldata.wrapper.api_wrapper import APIWrapper
from mldata.interpreters.interpreter import Interpreter

__author__ = 'Iván de Paz Centeno'


class Dataset(APIWrapper):
    def __init__(self, url_prefix, title, description, reference, tags, token=None, binary_interpreter=None, token_info=None):
        self.data = {}

        self.binary_interpreter = binary_interpreter
        """:type : Interpreter"""

        if "/" in url_prefix:
            self.data['url_prefix'] = url_prefix
        else:
            if token is not None:
                token_prefix = token.get_prefix()
                self.data['url_prefix'] = '{}/{}'.format(token_prefix, url_prefix)

        self.data['title'] = title
        self.data['description'] = description
        self.data['tags'] = tags
        self.data['reference'] = reference
        self.elements_count = 0
        self.comments_count = 0

        super().__init__(token, token_info=token_info)

    def set_binary_interpreter(self, binary_interpreter):
        self.binary_interpreter = binary_interpreter

    def get_url_prefix(self):
        return self.data['url_prefix']

    def get_description(self):
        return self.data['description']

    def get_title(self):
        return self.data['title']

    def get_tags(self):
        return self.data['tags']

    def get_reference(self):
        return self.data['reference']

    def set_description(self, new_desc):
        self.data['description'] = new_desc

    def set_title(self, new_title):
        self.data['title'] = new_title

    def set_tags(self, new_tags):
        self.data['tags'] = new_tags

    def set_reference(self, new_reference):
        self.data['reference'] = new_reference

    def update(self):
        self._patch_json("/datasets/{}".format(self.get_url_prefix()),
                         json_data={k:v for k,v in self.data.items() if k != "url_prefix"})

    @classmethod
    def from_dict(cls, definition, token, binary_interpreter=None, token_info=None):

        dataset = cls(definition['url_prefix'], definition['title'], definition['description'], definition['reference'],
                      definition['tags'], token=token, binary_interpreter=binary_interpreter, token_info=token_info)

        dataset.comments_count = definition['comments_count']
        dataset.elements_count = definition['elements_count']
        return dataset

    def add_element(self, title:str, description:str, tags:list, http_ref:str, content, interpret=True) -> Element:

        if type(content) is str:
            # content is a URI
            if not os.path.exists(content):
                raise Exception("content must be a binary data or a URI to a file.")

            with open(content, "rb") as f:
                content_bytes = f.read()

            if self.binary_interpreter is None:
                content = content_bytes
            else:
                content = self.binary_interpreter.cipher(content_bytes)

        result = self._post_json("datasets/{}/elements".format(self.get_url_prefix()), json_data={
            'title': title,
            'description': description,
            'tags': tags,
            'http_ref': http_ref,
        })

        self.refresh()

        element = self[result]
        element.set_content(content, interpret)
        return element

    def __getitem__(self, key) -> Element:
        try:
            result = self._get_json("datasets/{}/elements/{}".format(self.get_url_prefix(), key))
            raise_exception = False
        except Exception as ex:
            result = None
            raise_exception = True

        if raise_exception:
            raise KeyError(key)

        return Element.from_dict(result, self, self.token, self.binary_interpreter, token_info=self.token_info)

    def __delitem__(self, key):
        result = self._delete_json("datasets/{}/elements/{}".format(self.get_url_prefix(), key))
        self.refresh()

    def __iter__(self):
        """
        :rtype: Element
        :return:
        """
        page = 0

        # Two buffers to go through the elements. The second buffer will be filled whenever the first buffer is
        # half run.
        first = self._get_json("datasets/{}/elements".format(self.get_url_prefix()))
        second = []
        new_list_requested = False

        iteration = -1
        while len(first) > 0:
            iteration += 1

            if iteration > len(first)//2 and not new_list_requested:
                page += 1
                second = self._get_json("datasets/{}/elements".format(self.get_url_prefix()), extra_data={'page': page})
                new_list_requested = True

            if iteration >= len(first):
                first = second
                second = []
                iteration = 0
                new_list_requested = False

            if len(first) > iteration:
                yield Element.from_dict(first[iteration], self, self.token, self.binary_interpreter, token_info=self.token_info)

    def keys(self, page=-1):
        if page == -1:
            data = [element.get_id() for element in self]
        else:
            data = [element['_id'] for element in self._get_json("datasets/{}/elements".format(self.get_url_prefix()), extra_data={'page': page})]

        return data

    def __len__(self):
        return self.elements_count

    def __str__(self):
        return str(self.data)

    def save_to_folder(self, folder, metadata_format="json", elements_extension=None):
        try:
            os.mkdir(folder)
        except Exception as ex:
            pass

        format_saver = {
            "csv": self.__save_csv,
            "json": self.__save_json
        }

        if elements_extension is not None and elements_extension.startswith("."):
            elements_extension = elements_extension[1:]

        if metadata_format not in format_saver:
            raise Exception("format {} for metadata not supported.".format(metadata_format))

        print("Collecting metadata...")
        metadata = {}
        for element in self:
            if elements_extension is None:
                element_id = element.get_id()
            else:
                element_id = "{}.{}".format(element.get_id(), elements_extension)

            metadata[element_id] = {
                'id': element.get_id(),
                'title': element.get_title(),
                'description': element.get_description(),
                'http_ref': element.get_ref(),
                'tags': element.get_tags(),
            }

        format_saver[metadata_format](folder, metadata)
        print("Saved metadata in format {}".format(metadata_format))

        content_folder = os.path.join(folder, "content")
        try:
            os.mkdir(content_folder)
        except FileExistsError as ex:
            pass

        print("Fetching elements...")

        count = len(metadata)
        it = -1
        for filename, values in metadata.items():
            it += 1
            id = values['id']

            binary_content = self[id].get_content(interpret=False)
            with open(os.path.join(content_folder, filename), "wb") as f:
                f.write(binary_content)

            print("\rProgress: {}%".format(round(it/(count+0.0001)*100, 2)), end="", flush=True)

        print("\rProgress: 100%", end="", flush=True)
        print("\nFinished")

    def __save_json(self, folder, metadata):
        with open(os.path.join(folder, "metadata.json"), "w") as f:
            json.dump(metadata, f, indent=4)

    def __save_csv(self, folder, metadata):
        with open(os.path.join(folder, "metadata.csv"), 'w', newline="") as f:
            writer = csv.writer(f, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writerow(['file_name', 'id', 'title', 'description', 'http_ref', 'tags'])

            for k, v in metadata.items():
                writer.writerow([k, v['id'], v['title'], v['description'], v['http_ref'], ";".join(v['tags'])])

    def refresh(self):
        dataset_data = self._get_json("datasets/{}".format(self.get_url_prefix()))
        self.elements_count = dataset_data['elements_count']
        self.comments_count = dataset_data['comments_count']
        self.data = {k:dataset_data[k] for k in ['url_prefix', 'title', 'description', 'reference', 'tags']}
