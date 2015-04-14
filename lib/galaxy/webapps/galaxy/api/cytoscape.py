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
    def get_cys_from_history(self, trans, history_id, job_ids=None, dataset_ids=None, **kwds):
        """
        Generate cytoscape output for a workflow extracted from a given history.

        job_ids are the job ids associated with tools to be included in the cytoscape output.
        A list of job_ids parameter aren't not really required because they can be obtained
        for a given history using get_job_dict.
        """
        print "####################################"
        print "#### Working on history", history_id
        print "####################################"

        decoded_history_id = None
        if history_id is None:
            id = trans.history.id
            print "trans.history.id: ", id
        else:
            decoded_history_id = trans.security.decode_id(history_id)
            print "trans.security.decode_id: ", decoded_history_id

        dataset_ids = []
        # Find each job, for security we (implicately) check that they are
        # associated with a job in the current history.
        history = self.history_manager.get_accessible( trans, decoded_history_id, trans.user )
        jobs, warnings = summarize( trans, history )
        print "jobs from summarize:", jobs.keys()
        print "Jobs: ", jobs
        jobs_by_job_id = dict((job.id, job) for job in jobs.keys())
        print "jobs_by_job_id:", jobs_by_job_id
        print "history_id:", history_id, "is linked to job_ids:", jobs_by_job_id.keys()
        job_ids = jobs_by_job_id.keys()

        # Remove jobs that are data upload tasks
        print "################################################"
        print "#### Remove jobs that are data upload tasks ####"
        print "################################################"
        for job_id in job_ids:
            # Get the job object
            job = jobs_by_job_id[job_id]
            # Get tool and its parameters for the job
            tool = trans.app.toolbox.get_tool(job.tool_id)
            # Do not add tools which require user interaction into cytoscape output, the workflow
            # cannot run because of the user interaction. job_ids containing jobs that involve user
            # interactivity cannot be included in the extracted workflow. Their data output is
            # treated as an input dataset
            if tool.name == "Upload File":
                # Get output of this tool as an input dataset
                print "Upload job is: ", job
                # print "Output for data upload job:", job.get_output_datasets()
                for assoc in job.output_datasets:
                    print "job_to_output_data_association:", assoc
                    print "job_to_output_data_association name:", assoc.name
                    hda = assoc.dataset
                    print "Output dataset id is:", hda.dataset_id
                    print "Output hid is:", hda.hid
                    # Add to dataset_ids
                    dataset_ids.append(hda.hid)
                print "Removing job_id", job_id, "from cytoscape output since it is a data upload job"
                job_ids.remove(job_id)

        print "#################################"
        print "#### Create cytoscape output ####"
        print "#################################"
        dataset_collection_ids = None
        cy_workflow = self.extract_cys_nodes(trans, history_id=history_id, history=history, job_ids=job_ids, dataset_ids=dataset_ids, dataset_collection_ids=dataset_collection_ids)
        cy_wf = cy_workflow.to_json()
        # print cy_wf
        return cy_wf

    def extract_cys_nodes(self, trans, history_id=None, history=None, job_ids=None, dataset_ids=None, dataset_collection_ids=None):
        # Ensure job_ids and dataset_ids are lists (possibly empty)
        if job_ids is None:
            job_ids = []
        elif type(job_ids) is not list:
            job_ids = [job_ids]
        if dataset_ids is None:
            dataset_ids = []
        elif type(dataset_ids) is not list:
            dataset_ids = [dataset_ids]
        if dataset_collection_ids is None:
            dataset_collection_ids = []
        elif type(dataset_collection_ids) is not list:
            dataset_collection_ids = [ dataset_collection_ids]

        # Convert both sets of ids to integers
        job_ids = [ int( id ) for id in job_ids ]
        dataset_ids = [ int( id ) for id in dataset_ids ]
        dataset_collection_ids = [ int( id ) for id in dataset_collection_ids ]

        # Find each job, for security we (implicately) check that they are
        # associated with a job in the current history.
        summary = WorkflowSummary( trans, history )
        jobs = summary.jobs
        jobs_by_id = dict( ( job.id, job ) for job in jobs.keys() )

        print "history in extract_cys_nodes:", history
        print "history_id in extract_cys_nodes:", history_id
        print "summary in extract_cys_nodes:", summary
        print "jobs in extract_cys_nodes:", jobs
        print "jobs size:", jobs.__len__()
        print "jobs_by_id in extract_cys_nodes:", jobs_by_id
        print "jobs_by_id size:", jobs_by_id.__len__()
        if jobs.__len__() != jobs_by_id.__len__():
            print "Size of jobs_by_id does not equal size of jobs!"

        steps = []
        steps_by_job_id = {}
        hid_to_output_pair = {}

        #For cytoscape output
        steps_by_node_id = {}

        # For creating cytoscape object
        cy_workflow = Workflow(history_id)
        input_count = 0
        edge_count = 0

        # Input dataset steps
        for hid in dataset_ids:
            step = model.WorkflowStep()
            step.type = 'data_input'
            step.tool_inputs = dict(name="Input Dataset")
            hid_to_output_pair[hid] = (step, 'output')
            steps.append(step)
            print "Data input step:", step

            print "############################"
            print "#### Creating data node ####"
            print "############################"
            print "Order index (node id): ", step.id
            print "Step id (dataset_id): ", hid
            # Create data nodes for cytoscape output
            node_id = "n" + str(input_count)
            datanode = DataNode(node_id,
                                hid,
                                "data_input",
                                "data_input",
                                None,
                                ["output"])
            cy_workflow.nodes.append(datanode)
            steps_by_node_id[node_id] = step
            input_count += 1

        for hid in dataset_collection_ids:
            step = model.WorkflowStep()
            step.type = 'data_collection_input'
            if hid not in summary.collection_types:
                raise exceptions.RequestParameterInvalidException( "hid %s does not appear to be a collection" % hid )
            collection_type = summary.collection_types[ hid ]
            step.tool_inputs = dict( name="Input Dataset Collection", collection_type=collection_type )
            hid_to_output_pair[ hid ] = ( step, 'output' )
            steps.append( step )

        # Tool steps
        for job_id in job_ids:
            print "############################"
            print "#### Creating tool node ####"
            print "############################"

            print "job_id is:", job_id
            print "jobs_by_id:", jobs_by_id
            if job_id not in jobs_by_id:
                log.warn("job_id %s not found in jobs_by_id %s" % (job_id, jobs_by_id))
                raise AssertionError("Attempt to create workflow with job not connected to current history")

            job = jobs_by_id[job_id]
            print "Doing job_id", job_id, ":", job
            tool_inputs, associations = step_inputs(trans, job)

            step = model.WorkflowStep()
            step.type = 'tool'
            step.tool_id = job.tool_id
            step.tool_inputs = tool_inputs
            print "job.tool_id:", job.tool_id
            print "tool_inputs for tool_id", job.tool_id, ":", tool_inputs
            # The associations object contains the hda's hid and data input port name
            print "associations:", associations

            # List tool node outputs
            tool_node_outputs = []
            print "job tool_id:", job.tool_id
            job_outputs = job.output_datasets
            print "job_outputs", job_outputs
            for job_output in job_outputs:
                print "job_output.name:", job_output.name
                print "job_output.dataset:", job_output.dataset
                tool_node_outputs.append(job_output.name)

            # Create tool nodes for cytoscape workflow output
            tool_node_id = "n" + str(input_count)
            toolnode = ToolNode(tool_node_id,
                                job.tool_id,
                                job.tool_id,
                                "tool",
                                str(job_id),
                                tool_inputs,
                                tool_inputs,
                                tool_node_outputs)
            cy_workflow.nodes.append(toolnode)
            steps_by_node_id[tool_node_id] = step
            input_count += 1

            # NOTE: We shouldn't need to do two passes here since only
            #       an earlier job can be used as an input to a later
            #       job.
            print "#######################"
            print "#### Creating edge ####"
            print "#######################"
            print "steps_by_node_id:", steps_by_node_id
            conn = None

            print "associations:", associations
            print "hid_to_output_pair:", hid_to_output_pair
            # print "other_hid", other_hid
            for other_hid, input_name in associations:
                if job in summary.implicit_map_jobs:
                    an_implicit_output_collection = jobs[ job ][ 0 ][ 1 ]
                    input_collection = an_implicit_output_collection.find_implicit_input_collection( input_name )
                    if input_collection:
                        other_hid = input_collection.hid
                    else:
                        log.info("Cannot find implicit input collection for %s" % input_name)

                if other_hid in hid_to_output_pair:
                    other_step, other_name = hid_to_output_pair[ other_hid ]
                    conn = model.WorkflowStepConnection()
                    conn.input_step = step  # The current step
                    conn.input_name = input_name
                    # Should always be connected to an earlier step
                    conn.output_step = other_step
                    print "Source step:", conn.output_step
                    print "Source step dict:", other_step.__dict__
                    conn.output_name = other_name
                    print "Source step output port name:", conn.output_name
            steps.append(step)
            steps_by_job_id[job_id] = step

            # Store created dataset hids
            for assoc in (job.output_datasets + job.output_dataset_collection_instances):
                assoc_name = assoc.name
                if ToolOutputCollectionPart.is_named_collection_part_name( assoc_name ):
                    continue
                if job in summary.implicit_map_jobs:
                    hid = None
                    for implicit_pair in jobs[ job ]:
                        query_assoc_name, dataset_collection = implicit_pair
                        if query_assoc_name == assoc_name:
                            hid = dataset_collection.hid
                    if hid is None:
                        template = "Failed to find matching implicit job - job is %s, jobs are %s, assoc_name is %s."
                        message = template % ( job.id, jobs, assoc.name )
                        log.warn( message )
                        raise Exception("Failed to extract job.")
                else:
                    if hasattr( assoc, "dataset" ):
                        hid = assoc.dataset.hid
                    else:
                        hid = assoc.dataset_collection_instance.hid
                hid_to_output_pair[ hid ] = ( step, assoc.name )

            # Find source node id for edge by matching the input step
            # to steps in the workflow steps list
            source_node_id = None
            for node_id, theStep in steps_by_node_id.iteritems():
                if conn.output_step == theStep:
                    source_node_id = node_id
                    print "Matching node_id", node_id
                    print "Matching step", theStep

            print "job tool_id:", job.tool_id
            job_inputs = job.input_datasets
            print "job_inputs", job_inputs
            for job_input in job_inputs:
                print "job_input.name:", job_input.name
                print "job_input.dataset:", job_input.dataset

            edge_dataset_id = None
            for job_input in job_inputs:
                print job_input.name
                hda = job_input.dataset
                print "edge_dataset_id: ", hda.dataset_id
                edge_dataset_id = hda.dataset_id

            edge = Edge('e' + str(edge_count),
                        source_node_id,
                        conn.output_name,
                        tool_node_id,
                        conn.input_name,
                        edge_dataset_id)
            cy_workflow.edges.append(edge)
            edge_count += 1

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
                                                     ('output_ports', node.output_ports)])
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
