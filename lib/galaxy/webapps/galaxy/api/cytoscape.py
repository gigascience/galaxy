"""
API operations to obtain cytoscape output.

"""

import pkg_resources
import collections
import logging
import json

pkg_resources.require("Paste")

from galaxy import exceptions
from galaxy.web import _future_expose_api as expose_api
from galaxy.web import _future_expose_api_anonymous as expose_api_anonymous
from galaxy.web import _future_expose_api_raw as expose_api_raw

from galaxy.model.orm import eagerload_all

from galaxy.web.base.controller import BaseAPIController, UsesStoredWorkflowMixin
from galaxy.web.base.controller import UsesTagsMixin
from galaxy.web.base.controller import ExportsHistoryMixin
from galaxy.web.base.controller import ImportsHistoryMixin
from galaxy.web.base.controller import UsesVisualizationMixin

from galaxy.managers import histories, citations, workflows, hdas

from galaxy import util
from galaxy.util.odict import odict
from galaxy import exceptions
from galaxy import model
from galaxy.tools import ToolOutputCollectionPart

from galaxy.workflow.extract import summarize, WorkflowSummary, step_inputs
from galaxy.workflow.extract import extract_workflow

log = logging.getLogger(__name__)


class CytoscapeVisualizationsController(BaseAPIController, UsesTagsMixin, UsesStoredWorkflowMixin,
                                        ExportsHistoryMixin, ImportsHistoryMixin, UsesVisualizationMixin):
    def __init__(self, app):
        super(CytoscapeVisualizationsController, self).__init__(app)
        self.citations_manager = citations.CitationsManager(app)
        self.workflow_manager = workflows.WorkflowsManager( app )
        self.history_manager = histories.HistoryManager( app )
        self.hda_manager = hdas.HDAManager( app )

    @expose_api_raw
    def get_cys_from_workflow(self, trans, workflow_id, **kwds):
        """
        Generate cytoscape output for a workflow given a workflow id.
        """
        cy_workflow = Workflow(workflow_id)
        input_count = 0
        edge_count = 0
        step_id_node_id_dict = {}
        workflow_id = self.decode_id( workflow_id )
        query = trans.sa_session.query( trans.app.model.Workflow )
        workflow = query.get( workflow_id )
        if workflow is None:
            raise exceptions.ObjectNotFound( "No such workflow found." )
        for step in workflow.steps:
            # Create data nodes
            if step.type == 'data_input':
                data_node_id = "n" + str(input_count)
                datanode = DataNode(data_node_id, 0, "data_input", "data_input", 0, ["output"])
                cy_workflow.nodes.append(datanode)
                input_count += 1
                step_id_node_id_dict[step.id] = data_node_id
            else:
                # Create tool nodes
                tool = self.app.toolbox.get_tool( step.tool_id )
                tool_node_id = "n" + str(input_count)
                toolnode = ToolNode(tool_node_id, step.tool_id, tool.name, "tool", None, step.tool_inputs, step.tool_inputs, None)
                cy_workflow.nodes.append(toolnode)
                input_count += 1
                step_id_node_id_dict[step.id] = tool_node_id
                # Create edges
                for input_connection in step.input_connections:
                    start_step_num = input_connection.output_step_id
                    print "Source step number: ", start_step_num
                    start_step_num_output_port = input_connection.output_name
                    print "Source step output port name: ", start_step_num_output_port
                    output_port = input_connection.input_name
                    print "output port is: %s for step: %s" % (output_port, step)
                    edge = Edge('e' + str(edge_count),
                        step_id_node_id_dict[input_connection.output_step_id],
                        input_connection.output_name,
                        tool_node_id,
                        input_connection.input_name,
                        None)
                    cy_workflow.edges.append(edge)
                    edge_count += 1

        cy_workflow = cy_workflow.to_json()
        return cy_workflow

    @expose_api_raw
    def get_cys_from_history(self, trans, history_id, job_ids=None, dataset_ids=None, **kwds):
        """
        Generate cytoscape output for a workflow extracted from a given history.

        job_ids are the job ids associated with tools to be included in the
        cytoscape output. A list of job_ids are not really required because
        they can be obtained for a given history using get_job_dict.
        """
        print "####################################"
        print "#### Working on history", history_id
        print "####################################"
        # Get hold of jobs linked to the history_id
        decoded_history_id = None
        if history_id is None:
            id = trans.history.id
            print "trans.history.id: ", id
        else:
            decoded_history_id = trans.security.decode_id(history_id)
            print "trans.security.decode_id: ", decoded_history_id

        history = self.history_manager.get_accessible( decoded_history_id, trans.user )
        print "history:", history.to_dict()
        print "history active contents:", history.active_datasets
        jobs = []
        for hda in history.active_datasets:
            print "hda:", hda.to_dict()
            # Get job_to_output_dataset associations for the HDA
            print "job_associations:", hda.creating_job_associations
            # Get the job from the job_to_output_dataset association
            for job_to_output_dataset_association in hda.creating_job_associations:
                job = job_to_output_dataset_association.job
                print "job:", job.to_dict()
                jobs.append(job)

        # Create cytoscape data
        cy_workflow = Workflow(history_id)

        # Dictionary to hold job_id:node_id
        job_id_node_id_dict = {}
        # Dictionary to hold job_id:output_dataset_id
        output_dataset_id_job_id_dict = {}
        for job in jobs:
            for output_dataset in job.output_datasets:
                output_dataset_id_job_id_dict[output_dataset.dataset.dataset.id] = job.id
        print "job_id_output_dataset_id_dict", output_dataset_id_job_id_dict
        # Array of dataset ids which are inputs
        input_dataset_ids = []
        for job in jobs:
            for input_dataset in job.input_datasets:
                input_dataset_ids.append(input_dataset.dataset.dataset.id)
        print "input_dataset_ids:", input_dataset_ids


        # Create data and tool nodes
        input_count = 0
        edge_count = 0
        for job in jobs:
            # Create data nodes
            if job.tool_id == 'upload1':
                print "#### Data upload job ####"
                dataset_id = 0
                # Need to catch this exception check!
                if not job.input_datasets:
                    print "No input datasets!!"
                else:
                    for input_dataset in job.input_datasets:
                        print "input_dataset", input_dataset

                tool_outputs = []
                for output_dataset in job.output_datasets:
                    tool_outputs.append(output_dataset.name)
                    dataset_id = output_dataset.dataset.dataset.id
                data_node_id = "n" + str(input_count)
                datanode = DataNode(data_node_id,
                                    dataset_id,
                                    "data_input",
                                    "data_input",
                                    0,
                                    tool_outputs)
                cy_workflow.nodes.append(datanode)
                # Add entry into job_id:node_id dictionary
                job_id_node_id_dict[job.id] = data_node_id
                input_count += 1
            else:
                # Create tool nodes
                print "#### Creating tool node ####"
                tool = self.app.toolbox.get_tool( job.tool_id )
                # Parse tool inputs and outputs into an array
                tool_inputs = []
                for tool_input in tool.inputs:
                    tool_inputs.append(tool_input)
                tool_outputs = []
                for tool_output in tool.outputs:
                    tool_outputs.append(tool_output)
                tool_node_id = "n" + str(input_count)
                toolnode = ToolNode(tool_node_id,
                                    job.tool_id,
                                    tool.name,
                                    "tool",
                                    job.id,
                                    job.parameters,
                                    tool_inputs,
                                    tool_outputs)
                cy_workflow.nodes.append(toolnode)
                input_count += 1

                # Add entry into job_id:node_id dictionary
                job_id_node_id_dict[job.id] = tool_node_id

                # Create edges
                if job.input_datasets:
                    for input_dataset in job.input_datasets:
                        print "input_dataset", input_dataset
                        print "input dataset name:", input_dataset.name
                        print "input dataset id:", input_dataset.dataset.dataset.id
                        # Get job which has an output for the above dataset id
                        source_job_id = output_dataset_id_job_id_dict[input_dataset.dataset.dataset.id]
                        # Get output dataset name for the source_job_id
                        source_job_output_dataset_name = ""
                        for the_job in jobs:
                            if the_job.id == source_job_id:
                                print "the_job.output_datasets:", the_job.output_datasets
                                for the_job_output_dataset in the_job.output_datasets:
                                    print "the_job_output_dataset_name:", the_job_output_dataset.name
                                    source_job_output_dataset_name = the_job_output_dataset.name

                        print "source_job_id:", source_job_id
                        # Get node id for above source job id
                        source_node_id = job_id_node_id_dict[source_job_id]
                        print "source_node_id:", source_node_id
                        # Create edge
                        edge = Edge('e' + str(edge_count),
                                source_node_id,
                                source_job_output_dataset_name,
                                tool_node_id,
                                input_dataset.name,
                                input_dataset.dataset.dataset.id)
                        cy_workflow.edges.append(edge)
                        edge_count += 1

        # Create workflow output nodes
        # Find all jobs with output datasets that do not act as input
        for job in jobs:
            for output_dataset in job.output_datasets:
                if output_dataset.dataset.dataset.id not in input_dataset_ids:
                    print "Dataset id:", output_dataset.dataset.dataset.id, "does not act as an input dataset!!!"
                    # These output datasets of these jobs are output data nodes
                    print "#### Workflow output node ####"
                    output_data_node_id = "n" + str(input_count)
                    datanode = DataNode(output_data_node_id,
                                        output_dataset.dataset.dataset.id,
                                        "data_output",
                                        "data_output",
                                        "input_port_name",
                                        None)
                    cy_workflow.nodes.append(datanode)
                    input_count += 1

                    # Create edge
                    # Get job which has an output for the above dataset id
                    source_job_id = output_dataset_id_job_id_dict[output_dataset.dataset.dataset.id]
                    print "source_job_id:", source_job_id
                    # Get node id for above source job id
                    source_node_id = job_id_node_id_dict[source_job_id]
                    print "source_node_id:", source_node_id
                    # Create edge
                    edge = Edge('e' + str(edge_count),
                            source_node_id,
                            output_dataset.name,
                            output_data_node_id,
                            input_dataset.name,
                            output_dataset.dataset.dataset.id)
                    cy_workflow.edges.append(edge)
                    edge_count += 1

        cy_workflow = cy_workflow.to_json()
        return cy_workflow


class Workflow:
    """
    Model for representing workflows
    """
    def __init__(self, hist_id, wf_id=None, *args, **kwargs):
        self.wf_id = wf_id
        self.hist_id = hist_id
        self.delete = False
        self.name = None
        self.published = None
        self.nodes = []
        self.edges = []

    def to_json(self):
        nodes_dict = []
        edges_dict = []

        for node in self.nodes:
            if node.type == "data_input":
                node_data = collections.OrderedDict([('id', node.id),
                                                     ('name', node.name),
                                                     ('dataset_id', str(node.dataset_id)),
                                                     ('color', '#FCF8E3'),
                                                     ('output_ports', node.output_ports)])
            elif node.type == "data_output":
                node_data = collections.OrderedDict([('id', node.id),
                                                     ('name', node.name),
                                                     ('dataset_id', str(node.dataset_id)),
                                                     ('color', '#FCF8E3'),
                                                     ('input_ports', node.input_ports)])
            else:
                node_data = collections.OrderedDict([('id', node.id),
                                                     ('name', node.name),
                                                     ('job_id', node.job_id),
                                                     # ("params", node.params),
                                                     ("color", "#D9EDF7"),
                                                     ("input_ports", node.input_ports),
                                                     ("output_ports", node.output_ports)])
            nodes_dict.append({'data': node_data})

        for edge in self.edges:
            edge_data = collections.OrderedDict([('id', edge.edge_id),
                                                 ('dataset_id', edge.dataset_id),
                                                 ('weight', '1'),
                                                 ('source', edge.source_node_id),
                                                 ('source_node_output_port', edge.source_node_output_port),
                                                 ('target', edge.sink_node_id),
                                                 ('target_node_input_port', edge.sink_node_input_port)])
            edges_dict.append({"data": edge_data})

        content = {'nodes': nodes_dict, 'edges': edges_dict}
        elements_dict = {"elements": content}
        json_data = json.dumps(elements_dict, separators=(',', ':'), indent=2)
        return json_data

    def __str__(self):
        return self.wf_id

    def get_node_job_id(self, node_id):
        print "In get_node_job_id"
        print "Number of nodes in workflow: ", len(self.nodes)
        for node in self.nodes:
            print "node_id: ", node_id
            print "Checking node: ", node
            print node.id
            print node.type
            if node.id == node_id and node.type == "tool":
                print "Node: ", node, "has job_id: ", node.job_id
                return node.job_id
            else:
                continue


class Node:
    def __init__(self, id, name, type, input_ports, output_ports):
        self.id = id
        self.name = name
        self.type = type
        self.input_ports = input_ports
        self.output_ports = output_ports

    def __str__(self):
        return self.id


class DataNode(Node):
    def __init__(self, id, dataset_id, name, type, input_ports, output_ports):
        Node.__init__(self, id, name, type, input_ports, output_ports)
        self.dataset_id = dataset_id

    def __str__(self):
        return "DataNode: " + Node.__str__(self)


class ToolNode(Node):
    def __init__(self, id, tool_id, name, type, job_id, params, input_ports, output_ports):
        Node.__init__(self, id, name, type, input_ports, output_ports)
        self.tool_id = tool_id
        self.job_id = job_id
        self.params = params

    def __str__(self):
        return "ToolNode: " + Node.__str__(self)


class Edge:
    def __init__(self, edge_id, source_node_id, source_node_output_port, target_node_id, target_node_input_port, dataset_id):
        self.edge_id = edge_id
        self.source_node_id = source_node_id
        self.source_node_output_port = source_node_output_port
        self.sink_node_id = target_node_id
        self.sink_node_input_port = target_node_input_port
        self.dataset_id = dataset_id

    def __str__(self):
        return self.edge_id
