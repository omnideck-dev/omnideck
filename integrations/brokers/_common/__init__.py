"""Lifecycle helpers shared by integration broker processes.

The package defines common readiness signaling and process exit-code
conventions. Concrete brokers import the required submodules directly; this
package root is descriptive rather than a public facade.
"""
